#!/usr/bin/env python3
"""F7 · ¿Hay valor real contra el mercado? (opcional)

    ./.venv/bin/python scripts/09_value.py

ESTO ES ANALISIS, NO UNA RECOMENDACION DE APUESTA. Mide si las
probabilidades del modelo contienen informacion que el mercado no tenga ya en
el precio. No dice que apostar ni sugiere hacerlo.

LA DISTINCION QUE DEFINE ESTA FASE
----------------------------------
Medir contra la cuota de CIERRE dice si el modelo sabe algo. Medir contra la
cuota que estaba DISPONIBLE dice si eso se puede cobrar. No es lo mismo, y
confundirlas es como sale la mayoria de los backtests de apuestas que parecen
rentables: usan un precio que nadie podia tomar.

Se miden DOS escenarios:

    mejor cuota   maxh/maxd/maxa, el maximo entre todas las casas
    cuota media   avgh/avgd/avga, el promedio entre todas las casas

Y hay que decir algo del primero: NO es alcanzable. El 28.6% de los partidos
del periodo tiene margen negativo con esas cuotas, es decir arbitraje puro. Un
arbitraje real dura segundos; que aparezcan en uno de cada tres partidos
significa que Max* no es un conjunto de precios simultaneo, sino el maximo de
cada resultado por separado a lo largo de todo el pre-partido.

Se reporta igual, y a proposito: si el modelo pierde incluso con un escenario
imposiblemente favorable, la conclusion es mucho mas firme que si solo se
hubiera probado con precios realistas.

QUE ESPERAR, DICHO ANTES DE MIRAR
---------------------------------
El modelo pierde contra el mercado por 0.0230 de log-loss, y esa diferencia es
concluyente (p < 0.001). Un modelo peor que el mercado no puede tener ventaja
sistematica contra el mercado. Si este script encontrara ROI positivo, la
primera hipotesis seria un error en el script, no una mina de oro.

Se corre igual porque medirlo es distinto de suponerlo, y porque el CLV
(movimiento de la linea) puede mostrar valor en segmentos aunque el total no.
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, ledger, promotion    # noqa: E402
from marcador.backtest import ModelConfig               # noqa: E402
from marcador.config import LEAGUE                      # noqa: E402

# Bloque de prueba del modelo: no se uso para elegir nada.
TEST = ["2122", "2223", "2324", "2425", "2526"]
# El diagnostico de la F4 miro 2425-2627. Para probar una hipotesis que salio
# de ahi hay que usar temporadas que aquel no toco, o se estaria confirmando la
# pista con los mismos datos que la produjeron.
CLEAN_FOR_DIAGNOSTIC_HYPOTHESES = ["2122", "2223", "2324"]
OUTCOMES = ("H", "D", "A")
ODDS_BEST = {"H": "maxh", "D": "maxd", "A": "maxa"}
ODDS_AVG = {"H": "avgh", "D": "avgd", "A": "avga"}
ODDS_CLOSE = {"H": "avgch", "D": "avgcd", "A": "avgca"}


def load(con):
    cols = ", ".join(set(list(ODDS_BEST.values()) + list(ODDS_AVG.values())
                         + list(ODDS_CLOSE.values())))
    rows = con.execute(
        f"""SELECT match_id, season, ftr, {cols} FROM matches
            WHERE league = ? AND ftr IS NOT NULL""", (LEAGUE,)).fetchall()
    return {r["match_id"]: r for r in rows}


def devig(row, book):
    o = {k: row[book[k]] for k in OUTCOMES}
    if any(not v or v <= 1.0 for v in o.values()):
        return None
    inv = {k: 1 / v for k, v in o.items()}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()}, s


def simulate(bets, seed=0):
    """Stake plano de 1 unidad. Devuelve ROI y su intervalo por bootstrap."""
    if not bets:
        return None
    pnl = np.array([b["pnl"] for b in bets], float)
    rng = np.random.default_rng(seed)
    boots = pnl[rng.integers(0, len(pnl), size=(20000, len(pnl)))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"n": len(pnl), "roi": pnl.mean(), "lo": lo, "hi": hi,
            "clv": np.mean([b["clv"] for b in bets])}


def build_bets(preds, data, seasons, book, edge_min, only=None):
    out = []
    for match_id, probs, _ in preds:
        row = data.get(match_id)
        if row is None or row["season"] not in seasons:
            continue
        close = devig(row, ODDS_CLOSE)
        for k in OUTCOMES:
            if only and k != only:
                continue
            odds = row[book[k]]
            if not odds or odds <= 1.0:
                continue
            ev = probs[k] * odds - 1.0
            if ev <= edge_min:
                continue
            won = (row["ftr"] == k)
            # CLV: cuanto se movio la probabilidad implicita del mercado hacia
            # nosotros entre el momento de tomar el precio y el cierre. Es el
            # indicador adelantado: con pocas apuestas dice mas que el ROI,
            # porque no depende de si los resultados cayeron de cara o de cruz.
            clv = 0.0
            if close:
                taken = 1 / odds
                clv = close[0][k] - taken
            out.append({"pnl": (odds - 1.0) if won else -1.0, "clv": clv,
                        "ev": ev, "outcome": k})
    return out


def main():
    con = db.init_db()
    data = load(con)
    champ = promotion.read_champion()
    cfg = champ["config"] if champ else ModelConfig()
    matches = backtest.load_matches(con, LEAGUE)
    preds, _, _ = backtest.walk_forward(matches, TEST, cfg)
    print(f"Modelo {cfg.slug()} · {len(preds)} partidos "
          f"({TEST[0]}-{TEST[-1]})\n")

    # --- Cuanto margen tiene cada precio ------------------------------------
    over_best, over_avg, over_close = [], [], []
    for match_id, _, _ in preds:
        row = data.get(match_id)
        if not row:
            continue
        for acc, book in ((over_best, ODDS_BEST), (over_avg, ODDS_AVG),
                          (over_close, ODDS_CLOSE)):
            d = devig(row, book)
            if d:
                acc.append(d[1])
    print("Margen de la casa (suma de probabilidades implicitas; 1.00 = sin margen)")
    print(f"  mejor cuota disponible : {np.mean(over_best):.4f}  "
          f"-> {(np.mean(over_best)-1)*100:.2f}% de margen")
    print(f"  cuota promedio         : {np.mean(over_avg):.4f}  "
          f"-> {(np.mean(over_avg)-1)*100:.2f}%")
    print(f"  cierre promedio        : {np.mean(over_close):.4f}  "
          f"-> {(np.mean(over_close)-1)*100:.2f}%")
    arb = sum(1 for x in over_best if x < 1.0) / len(over_best)
    print(f"  El margen es el peaje: hay que superarlo ANTES de empezar a ganar.")
    print(f"  OJO: el {arb:.1%} de los partidos tiene margen NEGATIVO con la mejor")
    print(f"  cuota. Eso es arbitraje, y no existe: confirma que ese precio no")
    print(f"  era tomable de verdad.\n")

    # --- Estrategia principal -----------------------------------------------
    rows_out = []
    for book, label in ((ODDS_BEST, "MEJOR CUOTA (escenario imposible, ver arriba)"),
                        (ODDS_AVG, "CUOTA MEDIA (escenario realista)")):
        print(f"{label:40}{'apuestas':>10}{'ROI':>9}"
              f"{'IC 95% del ROI':>22}{'CLV medio':>11}")
        print("  " + "-" * 90)
        for edge in (0.00, 0.02, 0.05, 0.10):
            bets = build_bets(preds, data, TEST, book, edge)
            r = simulate(bets)
            if not r:
                continue
            rows_out.append((f"{label.split()[0]} EV>{edge:.0%}", r))
            print(f"  {'apostar cuando EV > ' + f'{edge:.0%}':38}{r['n']:>10}"
                  f"{r['roi']*100:>8.2f}%  [{r['lo']*100:>+7.2f}%,"
                  f"{r['hi']*100:>+7.2f}%]{r['clv']*100:>10.2f}%")
        allb = build_bets(preds, data, TEST, book, -9)
        r = simulate(allb)
        print(f"  {'control: apostar a TODO sin criterio':38}{r['n']:>10}"
              f"{r['roi']*100:>8.2f}%  [{r['lo']*100:>+7.2f}%,"
              f"{r['hi']*100:>+7.2f}%]{r['clv']*100:>10.2f}%\n")
    print("  El control es lo que produce el margen por si solo. Cualquier")
    print("  estrategia tiene que batir ESO, no batir el cero.\n")

    # --- La hipotesis del diagnostico ---------------------------------------
    print("HIPOTESIS DE LA F4: el modelo le gana al mercado en victorias visitantes.")
    print(f"Se prueba en {CLEAN_FOR_DIAGNOSTIC_HYPOTHESES[0]}-"
          f"{CLEAN_FOR_DIAGNOSTIC_HYPOTHESES[-1]}, temporadas que el diagnostico "
          f"no miro.\n")
    print(f"  {'':38}{'apuestas':>10}{'ROI':>9}{'IC 95% del ROI':>22}{'CLV medio':>11}")
    for label, only in (("solo visitante (A)", "A"), ("solo local (H)", "H")):
        bets = build_bets(preds, data, CLEAN_FOR_DIAGNOSTIC_HYPOTHESES,
                          ODDS_BEST, 0.0, only=only)
        r = simulate(bets)
        if not r:
            continue
        print(f"  {label + ', EV > 0':38}{r['n']:>10}{r['roi']*100:>8.2f}%"
              f"  [{r['lo']*100:>+7.2f}%,{r['hi']*100:>+7.2f}%]{r['clv']*100:>10.2f}%")

    # --- Veredicto -----------------------------------------------------------
    main_bets = build_bets(preds, data, TEST, ODDS_AVG, 0.0)
    r = simulate(main_bets)
    print(f"\n  VEREDICTO")
    positive = r["lo"] > 0
    if positive:
        print(f"    ROI {r['roi']*100:+.2f}% con el intervalo entero por encima de")
        print(f"    cero. Antes de creerlo: revisar el script buscando un error,")
        print(f"    porque contradice que el modelo pierda contra el mercado.")
    else:
        print(f"    Con cuotas realistas: ROI {r['roi']*100:+.2f}%, intervalo "
              f"[{r['lo']*100:+.2f}%, {r['hi']*100:+.2f}%].")
        print(f"    No hay ventaja demostrable.")
        print(f"    Es el resultado que anticipaba el log-loss: un modelo peor")
        print(f"    que el mercado no puede batir al mercado de forma sistematica.")

    import csv
    path = ledger.LEDGER_DIR / "value.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["estrategia", "apuestas", "roi", "ci_low", "ci_high", "clv"])
        for label, s in rows_out:
            wr.writerow([label, s["n"], f"{s['roi']:.6f}", f"{s['lo']:.6f}",
                         f"{s['hi']:.6f}", f"{s['clv']:.6f}"])
    print(f"\n  Guardado en ledger/value.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
