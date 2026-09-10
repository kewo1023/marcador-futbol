#!/usr/bin/env python3
"""Los cuatro mercados sobre las CINCO ligas: re-afinar `w` y volver a medir.

    ./.venv/bin/python scripts/12_markets_multi.py

POR QUE EXISTE APARTE DE 08
---------------------------
`08_markets.py` midio los mercados sobre la Premier y sus numeros estan en el
README y en `ledger/markets.csv`. No se tocan. Este script repite el mismo
procedimiento sobre las cinco ligas y escribe en `ledger/markets_multi.csv`,
para que las dos tablas se lean una al lado de la otra.

LO QUE SE RE-AFINA, Y COMO
--------------------------
`w` es cuanto se le cree al modelo frente a la frecuencia base:
p = w*modelo + (1-w)*base. La F5 lo eligio sobre una liga, y desde el
2026-09-10 el mercado de tarjetas corre EN VIVO con ese `w` heredado. Aqui se
elige de nuevo con las perdidas de las cinco ligas juntas — el mismo criterio
que el gate: cada liga se ajusta por separado, las perdidas por partido se
agrupan.

Se reporta ademas el `w` que elegiria cada liga por su cuenta. Si los cinco
coinciden, el `w` global es una propiedad del mercado; si se dispersan, es un
promedio que a alguna liga le queda mal, y hay que saberlo antes de ponerlo en
produccion.

LA REGLA 6, COMO SIEMPRE
------------------------
El bloque de afinado (2122-2324) elige `w`; el de prueba (2425-2526) mide. Y
'gana a la base' se decide con el bootstrap pareado sobre las perdidas
agrupadas, no con el promedio. Con una liga, ninguna linea de goles, corners o
tiros era concluyente; con cinco veces mas partidos, lo que era ruido puede
dejar de serlo — en cualquiera de las dos direcciones.
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, ledger, promotion       # noqa: E402
from marcador.backtest import ModelConfig                  # noqa: E402
from marcador.config import LEAGUES, LIVE_MARKETS, league_label  # noqa: E402
from marcador.markets import MARKETS, market_code          # noqa: E402
from marcador.scoring import bootstrap_diff                # noqa: E402

TUNE = ["2122", "2223", "2324"]
TEST = ["2425", "2526"]
W_GRID = np.arange(0.0, 1.01, 0.1)
EPS = 1e-15


def loss(p, a):
    return -math.log(max(p[a], EPS))


def base_rate(matches, line, seasons):
    """Frecuencia de OVER con lo anterior a cada temporada, dentro de la liga."""
    out = {}
    for season in seasons:
        past = [m for m in matches if m["season"] < season]
        if not past:
            continue
        r = sum(1 for m in past if m["total"] > line) / len(past)
        for m in matches:
            if m["season"] == season:
                out[m["id"]] = {"OVER": r, "UNDER": 1 - r}
    return out


def blend(p_model, p_base, w):
    return {k: w * p_model[k] + (1 - w) * p_base[k] for k in ("OVER", "UNDER")}


def best_w(items):
    """`items` = [(p_model, p_base, actual), ...]. El w que minimiza la
    perdida media del blend sobre esa lista."""
    return float(min(W_GRID, key=lambda w: sum(
        loss(blend(pm, pb, w), a) for pm, pb, a in items) / len(items)))


def main():
    con = db.init_db()
    champ = promotion.read_champion()
    cfg_base = champ["config"] if champ else ModelConfig()
    leagues = list(LEAGUES)
    print(f"Motor: {cfg_base.slug()} · {len(leagues)} ligas")
    print(f"w se elige en {TUNE[0]}-{TUNE[-1]} y se reporta en "
          f"{TEST[0]}-{TEST[-1]}\n")

    live_w = {m.key: LIVE_MARKETS[m.key]["w"] for m in MARKETS
              if m.key in LIVE_MARKETS}
    rows_out = []
    for market in MARKETS:
        cfg = ModelConfig(xi=cfg_base.xi, reg=cfg_base.reg,
                          use_rho=market.use_rho, refit_days=cfg_base.refit_days)
        # Un walk-forward por liga sobre TUNE+TEST de una vez: es secuencial,
        # asi que equivale a dos llamadas y cuesta la mitad.
        per_league = {}
        for lg in leagues:
            matches = backtest.load_market_matches(con, lg, market)
            probs, n_fits = backtest.walk_forward_market(matches, TUNE + TEST,
                                                         cfg, market.lines)
            per_league[lg] = (matches, probs, n_fits)

        print(f"{market.label.upper()}  "
              f"({sum(v[2] for v in per_league.values())} reajustes)")
        print(f"  {'linea':>6}{'w 5 ligas':>11}{'w por liga (' + ' '.join(leagues) + ')':>34}"
              f"{'w F5':>6}{'base':>9}{'encogido':>10}{'gana':>9}"
              f"{'IC 95%':>20}{'':>4}")

        for line in market.lines:
            tune_items, test_by_league = [], {}
            w_league = {}
            for lg, (matches, probs, _) in per_league.items():
                bT = base_rate(matches, line, TUNE)
                bE = base_rate(matches, line, TEST)
                items_T = [(probs[line][m["id"]], bT[m["id"]],
                            "OVER" if m["total"] > line else "UNDER")
                           for m in matches if m["season"] in TUNE and m["id"] in bT]
                items_E = [(probs[line][m["id"]], bE[m["id"]],
                            "OVER" if m["total"] > line else "UNDER")
                           for m in matches if m["season"] in TEST and m["id"] in bE]
                tune_items += items_T
                test_by_league[lg] = items_E
                w_league[lg] = best_w(items_T) if items_T else float("nan")

            # w se elige SOLO con el bloque de afinado, y con las cinco juntas.
            w_all = best_w(tune_items)

            # Prueba: perdidas por partido, encogido vs base, agrupadas.
            l_shr, l_base = [], []
            for items in test_by_league.values():
                for pm, pb, a in items:
                    l_shr.append(loss(blend(pm, pb, w_all), a))
                    l_base.append(loss(pb, a))
            d, lo, hi, p, n = bootstrap_diff(l_shr, l_base)
            ll_base = sum(l_base) / n
            ll_shr = sum(l_shr) / n
            gain = ll_base - ll_shr
            concl = (lo > 0) == (hi > 0)
            mark = "  <- real" if concl and gain > 0 else (
                   "  <- PIERDE" if gain < 0 else "")
            w_f5 = live_w.get(market.key, {}).get(line)
            print(f"  {line:>6}{w_all:>11.1f}"
                  f"{' '.join(f'{w_league[lg]:.1f}' for lg in leagues):>34}"
                  f"{(f'{w_f5:.1f}' if w_f5 is not None else '-'):>6}"
                  f"{ll_base:>9.4f}{ll_shr:>10.4f}{gain:>+9.4f}"
                  f"   [{-hi:>+7.4f},{-lo:>+7.4f}]{mark}")

            rows_out.append({
                "mercado": market_code(market, line), "etiqueta": market.label,
                "linea": line, "ligas": " ".join(leagues), "n": n,
                "w": f"{w_all:.1f}",
                "w_por_liga": " ".join(f"{lg}:{w_league[lg]:.1f}" for lg in leagues),
                "w_f5_una_liga": f"{w_f5:.1f}" if w_f5 is not None else "",
                "log_loss_base": f"{ll_base:.6f}",
                "log_loss_encogido": f"{ll_shr:.6f}",
                "gana_a_base": f"{gain:.6f}",
                "ci_low": f"{-hi:.6f}", "ci_high": f"{-lo:.6f}",
                "p_value": f"{p:.4f}", "concluyente": "si" if concl else "no",
            })
        print()

    print(f"{'RESUMEN — le gana a la frecuencia base en 5 ligas?':52}"
          f"{'dif.':>9}{'p':>8}{'n':>7}")
    print("  " + "-" * 76)
    for r in rows_out:
        ok = "SI" if r["concluyente"] == "si" and float(r["gana_a_base"]) > 0 else "no"
        print(f"  {r['etiqueta'] + ' ' + str(r['linea']):50}"
              f"{float(r['gana_a_base']):>+9.4f}{float(r['p_value']):>8.3f}"
              f"{r['n']:>7}  {ok}")

    # --- Lo que importa para produccion ------------------------------------
    print("\n  EL w DE TARJETAS EN VIVO")
    for r in rows_out:
        if not r["mercado"].startswith("TARJETAS_"):
            continue
        same = r["w"] == r["w_f5_una_liga"]
        print(f"    {r['linea']:>4}: F5 (Premier) {r['w_f5_una_liga']} -> "
              f"5 ligas {r['w']}  {'igual' if same else 'CAMBIA'}"
              f"   por liga: {r['w_por_liga']}")

    path = ledger.LEDGER_DIR / "markets_multi.csv"
    ledger.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
        wr.writeheader(); wr.writerows(rows_out)
    print(f"\n  Guardado en {path.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
