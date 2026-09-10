#!/usr/bin/env python3
"""F3 · Ingiere resultados, los cruza con lo predicho y recalcula el marcador.

    ./.venv/bin/python scripts/05_score.py

Es la otra mitad del ciclo. Corre a diario en GitHub Actions, despues de que se
juegan los partidos.

Lo que mide aqui es el TRACK RECORD EN VIVO: predicciones emitidas antes del
kickoff, sin saber el resultado. Es distinto del backtest, y vale mas: un
backtest lo puede inflar cualquiera sin darse cuenta, un track record en vivo
no, porque las predicciones ya estaban escritas y versionadas.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import db, ingest, ledger, scoring          # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES, market_probs  # noqa: E402
from marcador.config import CURRENT_SEASON, LEAGUES       # noqa: E402

# El mismo nombre con el que 02_baseline registra el mercado en el backtest,
# para que 'test' y 'live' de la misma referencia se lean uno al lado del otro.
MARKET_REFERENCE = "market-avgclose-v1"


def refresh(con):
    """Re-baja la temporada en curso de las cinco ligas."""
    n = 0
    for league in LEAGUES:
        path = ingest.download_season(CURRENT_SEASON, league=league, force=True)
        n += ingest.upsert_matches(
            con, ingest.rows_from_csv(path, league, CURRENT_SEASON))
    return n


def collect_results(con, predicted_ids):
    """Los resultados de los partidos que ya habiamos predicho.

    Solo esos. El ledger no es una copia de la fuente: guarda lo minimo para
    que cualquiera pueda verificar el marcador sin bajarse nada (regla 2).
    """
    if not predicted_ids:
        return []
    out, ids = [], sorted(predicted_ids)
    now = ledger.now_iso()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in con.execute(
                f"""SELECT match_id, match_date, home_team, away_team,
                           fthg, ftag, ftr,
                           avgch, avgcd, avgca, psch, pscd, psca
                    FROM matches WHERE ftr IS NOT NULL AND match_id IN ({q})""",
                chunk):
            # La probabilidad del mercado va con el resultado, no con la
            # prediccion: es la cuota de CIERRE, y solo existe cuando el
            # partido ya se jugo. Sin ella, el dashboard solo podria comparar
            # contra Elo del backtest, que no es el techo de nada.
            mkt = market_probs(r) or {}
            out.append({"match_id": r["match_id"], "match_date": r["match_date"],
                        "home_team": r["home_team"], "away_team": r["away_team"],
                        "fthg": r["fthg"], "ftag": r["ftag"], "ftr": r["ftr"],
                        "market_h": f"{mkt['H']:.6f}" if mkt else "",
                        "market_d": f"{mkt['D']:.6f}" if mkt else "",
                        "market_a": f"{mkt['A']:.6f}" if mkt else "",
                        "recorded_at": now})
    return out


def score_live():
    """Calcula el marcador leyendo SOLO el ledger, sin tocar la base.

    Es a proposito: el ledger es lo que esta versionado y lo que cualquiera
    puede auditar. Si el marcador se pudiera calcular solo con la base local,
    nadie de afuera podria comprobarlo.
    """
    preds = [p for p in ledger.read_predictions() if p["mode"] == "live"]
    rows = {r["match_id"]: r for r in ledger.read_results()}
    results = {k: r["ftr"] for k, r in rows.items()}

    by_model = {}
    for p in preds:
        if p["match_id"] not in results:
            continue                      # todavia no se juega: no cuenta
        slot = by_model.setdefault(p["model_version"], {})
        m = slot.setdefault(p["match_id"], {"probs": {}, "ftr": results[p["match_id"]]})
        m["probs"][p["outcome"]] = float(p["prob"])

    # El mercado se evalua sobre EXACTAMENTE los partidos que el modelo tiene
    # completos y con cuota, y con el mismo nombre que ya usa la referencia
    # del backtest. Es el techo del proyecto; sin el, 'log-loss en vivo' es un
    # numero suelto que solo se puede comparar con Elo, y Elo no es el techo
    # de nada.
    for model_version, matches in list(by_model.items()):
        mk = {}
        for mid, m in matches.items():
            r = rows[mid]
            if len(m["probs"]) == len(OUTCOMES) and r.get("market_h"):
                mk[mid] = {"probs": {"H": float(r["market_h"]),
                                     "D": float(r["market_d"]),
                                     "A": float(r["market_a"])},
                           "ftr": m["ftr"]}
        if mk:
            by_model[MARKET_REFERENCE] = mk

    out = []
    for model_version, matches in by_model.items():
        pairs = [(m["probs"], m["ftr"]) for m in matches.values()
                 if len(m["probs"]) == len(OUTCOMES)]
        if not pairs:
            continue
        res = scoring.evaluate([p for p, _ in pairs], [a for _, a in pairs])
        out.append({"model_version": model_version, "market": MARKET_1X2,
                    "eval_set": "live", "n_matches": res["n_matches"],
                    "log_loss": f"{res['log_loss']:.6f}",
                    "brier": f"{res['brier']:.6f}",
                    "accuracy": f"{res['accuracy']:.6f}",
                    "computed_at": ledger.now_iso()})
    return out, by_model


def find_missed(con, preds):
    """Partidos jugados que el sistema nunca predijo.

    ES LA COMPROBACION QUE FALTABA. La ventana de fixtures de la fuente cubre
    pocos dias, asi que el loop depende de correr con suficiente frecuencia
    para agarrar cada partido mientras esta dentro de esa ventana. Esa
    dependencia no se puede dar por buena: hay que medirla.

    El alcance arranca en la fecha del primer partido que SI se predijo en
    vivo. Antes de eso el sistema no existia y no tiene sentido reclamarle
    cobertura.
    """
    live = [p for p in preds if p["mode"] == "live"]
    if not live:
        return []
    since = min(p["match_date"] for p in live)
    predicted = {p["match_id"] for p in live}
    q = ",".join("?" * len(LEAGUES))
    rows = con.execute(
        f"""SELECT match_id, match_date, home_team, away_team, ftr
            FROM matches
            WHERE league IN ({q}) AND ftr IS NOT NULL AND match_date >= ?
            ORDER BY match_date""", list(LEAGUES) + [since]).fetchall()
    now = ledger.now_iso()
    return [{"match_id": r["match_id"], "match_date": r["match_date"],
             "home_team": r["home_team"], "away_team": r["away_team"],
             "ftr": r["ftr"], "detected_at": now}
            for r in rows if r["match_id"] not in predicted]


# Codigo de salida propio: el trabajo se hizo, pero hay un agujero de cobertura
# que alguien tiene que ver. El workflow commitea primero y falla despues.
EXIT_MISSED = 3


def main():
    con = db.init_db()
    n = refresh(con)
    print(f"Temporada en curso re-ingestada: {n} partidos\n")

    predicted = ledger.predicted_matches()
    added = ledger.upsert_results(collect_results(con, predicted))
    pending = len(predicted) - len(ledger.read_results())
    print(f"Resultados: {added} nuevos registrados · "
          f"{len(ledger.read_results())} en total · {pending} partidos aun sin jugar")

    missed = find_missed(con, ledger.read_predictions())
    n_missed = ledger.record_missed(missed) if missed else 0

    metrics, by_model = score_live()
    if not metrics:
        print("\nTodavia no hay ningun partido predicho Y jugado. "
              "El marcador en vivo arranca cuando se juegue el primero.")
        return 0

    ledger.upsert_metrics(metrics)
    print(f"\n{'TRACK RECORD EN VIVO':40}{'log-loss':>10}{'Brier':>9}"
          f"{'acc':>8}{'n':>6}")
    print("  " + "-" * 71)
    for m in sorted(metrics, key=lambda r: float(r["log_loss"])):
        print(f"  {m['model_version']:38}{float(m['log_loss']):>10.4f}"
              f"{float(m['brier']):>9.4f}{float(m['accuracy'])*100:>7.1f}%"
              f"{m['n_matches']:>6}")

    # Contexto: sin una referencia, un log-loss suelto no dice nada. La que
    # importa es el mercado sobre ESTOS partidos (ya esta en la tabla de
    # arriba si hubo cuota); Elo del backtest queda como segunda referencia.
    live = {m["model_version"]: m for m in metrics}
    mkt = live.get(MARKET_REFERENCE)
    models = [m for m in metrics if m["model_version"] != MARKET_REFERENCE]
    if mkt and models:
        for m in models:
            d = float(m["log_loss"]) - float(mkt["log_loss"])
            print(f"\n  {m['model_version']} contra el mercado, mismos "
                  f"{mkt['n_matches']} partidos: {d:+.4f} "
                  f"({'pierde' if d > 0 else 'gana'})")
    ref = {r["eval_set"] + "|" + r["model_version"]: r
           for r in ledger._read(ledger.LEDGER_METRICS)}
    base = ref.get("test|baseline-elo-v1")
    if base:
        print(f"  Referencia del backtest — Elo: {float(base['log_loss']):.4f}")
    print("  Ojo: con pocos partidos este numero se mueve muchisimo. "
          "No significa nada hasta tener ~100, y la diferencia contra el")
    print("  mercado no es concluyente hasta que pase por el bootstrap (regla 6).")

    if missed:
        print(f"\n  {'!' * 60}")
        print(f"  {len(missed)} PARTIDOS SE JUGARON SIN PREDICCION "
              f"({n_missed} nuevos)")
        for m in missed[:10]:
            print(f"    {m['match_date']}  {m['home_team']} vs {m['away_team']}")
        print(f"\n  Quedaron registrados en ledger/missed.csv. Un agujero en el")
        print(f"  track record no se puede tapar despues: el partido ya se jugo.")
        print(f"  Causa mas probable: la ventana de fixtures de la fuente no los")
        print(f"  cubrio a tiempo, o el job de predecir fallo ese dia.")
        print(f"  {'!' * 60}")
        return EXIT_MISSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
