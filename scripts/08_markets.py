#!/usr/bin/env python3
"""F5 · Los cuatro mercados sobre un solo motor.

    ./.venv/bin/python scripts/08_markets.py

Aqui se cobra la decision de la F2 de escribir Dixon-Coles a mano: cambiar de
mercado es cambiar de que columna salen los dos conteos. El motor no sabe si
cuenta goles, corners, tarjetas o tiros.

TRES COSAS QUE SOLO APARECEN AL MEDIRLO
---------------------------------------
1. Poisson no basta en todos lados. La dispersion residual da 0.86 en goles y
   amarillas y 0.99 en tiros a puerta, pero 1.34 en corners y 1.46 en tiros
   totales. En esos dos la distribucion predictiva pasa a binomial negativa;
   la media la sigue estimando el mismo motor.

2. El modelo crudo PIERDE contra la frecuencia base en corners. La senal
   existe (correlacion 0.119, comparable a la de goles) pero es debil frente
   al ruido, y la confianza de mas cuesta mas de lo que aporta la senal.
   Se corrige encogiendo hacia la base: p = w*modelo + (1-w)*base.

3. w se elige por mercado en el bloque de afinado, nunca en el de prueba. El
   valor que sale mide cuanto se le puede creer al modelo en ese mercado, y
   reproduce por una via independiente el orden de la senal.

EL TECHO: DONDE HAY Y DONDE NO
------------------------------
La fuente publica cuotas de cierre para 1X2 y over/under 2.5 goles, y para
nada mas. Corners, tarjetas y tiros se miden solo contra la frecuencia base:
se sabe si el modelo aporta, no cuanto le falta para lo alcanzable. Es una
medicion mas debil y se reporta como tal.
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, ledger, promotion       # noqa: E402
from marcador.backtest import ModelConfig                  # noqa: E402
from marcador.config import LEAGUE                         # noqa: E402
from marcador.markets import MARKETS, market_code, ou_market_probs  # noqa: E402
from marcador.scoring import bootstrap_diff                # noqa: E402

TUNE = ["2122", "2223", "2324"]
TEST = ["2425", "2526"]
W_GRID = np.arange(0.0, 1.01, 0.1)
EPS = 1e-15


def logloss(probs, actual):
    return sum(-math.log(max(p[a], EPS)) for p, a in zip(probs, actual)) / len(actual)


def losses(probs, actual):
    return [-math.log(max(p[a], EPS)) for p, a in zip(probs, actual)]


def base_rate(matches, line, seasons):
    """Frecuencia base de 'over', recalculada con lo anterior a cada temporada."""
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


def blend(model, base, w):
    return {i: {k: w * model[i][k] + (1 - w) * base[i][k] for k in ("OVER", "UNDER")}
            for i in model if i in base}


def main():
    con = db.init_db()
    champ = promotion.read_champion()
    cfg_base = champ["config"] if champ else ModelConfig()
    print(f"Motor: {cfg_base.slug()}")
    print(f"w se elige en {TUNE[0]}-{TUNE[-1]} y se reporta en {TEST[0]}-{TEST[-1]}\n")

    rows_out = []
    for market in MARKETS:
        matches = backtest.load_market_matches(con, LEAGUE, market)
        cfg = ModelConfig(xi=cfg_base.xi, reg=cfg_base.reg,
                          use_rho=market.use_rho, refit_days=cfg_base.refit_days)
        p_tune, _ = backtest.walk_forward_market(matches, TUNE, cfg, market.lines)
        p_test, n_fits = backtest.walk_forward_market(matches, TEST, cfg, market.lines)
        tg_tune = [m for m in matches if m["season"] in TUNE]
        tg_test = [m for m in matches if m["season"] in TEST]

        print(f"{market.label.upper()}  ({n_fits} reajustes)")
        print(f"  {'linea':>7}{'w*':>6}{'base':>9}{'modelo':>9}{'encogido':>10}"
              f"{'mercado':>10}{'gana a base':>13}")
        for line in market.lines:
            bT = base_rate(matches, line, TUNE)
            bE = base_rate(matches, line, TEST)
            aT = ["OVER" if m["total"] > line else "UNDER" for m in tg_tune]
            aE = ["OVER" if m["total"] > line else "UNDER" for m in tg_test]

            # w se elige SOLO con el bloque de afinado.
            best_w = min(W_GRID, key=lambda w: logloss(
                [blend(p_tune[line], bT, w)[m["id"]] for m in tg_tune], aT))

            shrunk = blend(p_test[line], bE, best_w)
            ll_base = logloss([bE[m["id"]] for m in tg_test], aE)
            ll_model = logloss([p_test[line][m["id"]] for m in tg_test], aE)
            ll_shr = logloss([shrunk[m["id"]] for m in tg_test], aE)

            mkt_txt, ll_mkt = "  sin techo", None
            if market.has_market_odds:
                pairs = [(ou_market_probs(m, line), a) for m, a in zip(tg_test, aE)]
                pairs = [(p, a) for p, a in pairs if p]
                if len(pairs) > 100:
                    ll_mkt = logloss([p for p, _ in pairs], [a for _, a in pairs])
                    mkt_txt = f"{ll_mkt:>10.4f}"

            gain = ll_base - ll_shr
            flag = "" if gain > 0 else "   <- PIERDE"
            print(f"  {line:>7}{best_w:>6.1f}{ll_base:>9.4f}{ll_model:>9.4f}"
                  f"{ll_shr:>10.4f}{mkt_txt}{gain:>+13.4f}{flag}")

            d, lo, hi, p, n = bootstrap_diff(
                losses([shrunk[m["id"]] for m in tg_test], aE),
                losses([bE[m["id"]] for m in tg_test], aE))
            rows_out.append({
                "mercado": market_code(market, line), "etiqueta": market.label,
                "linea": line, "n": len(tg_test), "w": f"{best_w:.1f}",
                "log_loss_base": f"{ll_base:.6f}",
                "log_loss_modelo": f"{ll_model:.6f}",
                "log_loss_encogido": f"{ll_shr:.6f}",
                "log_loss_mercado": f"{ll_mkt:.6f}" if ll_mkt else "",
                "gana_a_base": f"{gain:.6f}", "ci_low": f"{lo:.6f}",
                "ci_high": f"{hi:.6f}", "p_value": f"{p:.4f}",
                "concluyente": "si" if (lo > 0) == (hi > 0) else "no",
            })
        print()

    print(f"{'RESUMEN — le gana a la frecuencia base?':46}{'dif.':>9}{'p':>8}")
    print("  " + "-" * 66)
    for r in rows_out:
        mark = "SI" if r["concluyente"] == "si" and float(r["gana_a_base"]) > 0 else "no"
        print(f"  {r['etiqueta'] + ' ' + str(r['linea']):44}"
              f"{-float(r['gana_a_base']):>+9.4f}{float(r['p_value']):>8.3f}  {mark}")

    path = ledger.LEDGER_DIR / "markets.csv"
    ledger.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
        wr.writeheader(); wr.writerows(rows_out)
    print(f"\nGuardado en ledger/markets.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
