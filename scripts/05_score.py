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

from marcador import db, ingest, ledger, live_markets, scoring  # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES, market_probs  # noqa: E402
from marcador.markets import ou_market_probs               # noqa: E402
from marcador.config import (BASE_MODEL_VERSION, CURRENT_SEASON,  # noqa: E402
                             LEAGUES)

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
                           fthg, ftag, ftr, hy, ay, hst, ast,
                           avgch, avgcd, avgca, psch, pscd, psca,
                           avgc_o25, avgc_u25
                    FROM matches WHERE ftr IS NOT NULL AND match_id IN ({q})""",
                chunk):
            # La probabilidad del mercado va con el resultado, no con la
            # prediccion: es la cuota de CIERRE, y solo existe cuando el
            # partido ya se jugo. Sin ella, el dashboard solo podria comparar
            # contra Elo del backtest, que no es el techo de nada.
            mkt = market_probs(r) or {}
            ou = ou_market_probs(r, 2.5) or {}
            out.append({"match_id": r["match_id"], "match_date": r["match_date"],
                        "home_team": r["home_team"], "away_team": r["away_team"],
                        "fthg": r["fthg"], "ftag": r["ftag"], "ftr": r["ftr"],
                        "market_h": f"{mkt['H']:.6f}" if mkt else "",
                        "market_d": f"{mkt['D']:.6f}" if mkt else "",
                        "market_a": f"{mkt['A']:.6f}" if mkt else "",
                        "market_o25": f"{ou['OVER']:.6f}" if ou else "",
                        "market_u25": f"{ou['UNDER']:.6f}" if ou else "",
                        "yellows": (r["hy"] + r["ay"]
                                    if r["hy"] is not None and r["ay"] is not None
                                    else ""),
                        "sot": (r["hst"] + r["ast"]
                                if r["hst"] is not None and r["ast"] is not None
                                else ""),
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

    def actual_for(market, r):
        """Lo que paso, en el vocabulario del mercado. None si falta el dato."""
        if market == MARKET_1X2:
            return r["ftr"]
        parsed = live_markets.parse_market(market)
        if not parsed:
            return None
        total = live_markets.actual_total(parsed[0], r)
        return None if total is None else live_markets.actual_outcome(total, parsed[1])

    # Agrupado por (modelo, mercado): cada mercado tiene sus propios outcomes
    # (H/D/A o OVER/UNDER) y su propia columna de verdad en results.csv.
    by_key = {}
    for p in preds:
        r = rows.get(p["match_id"])
        if r is None:
            continue                      # todavia no se juega: no cuenta
        actual = actual_for(p["market"], r)
        if actual is None:
            continue                      # se jugo, pero sin ese dato
        slot = by_key.setdefault((p["model_version"], p["market"]), {})
        m = slot.setdefault(p["match_id"], {"probs": {}, "actual": actual})
        m["probs"][p["outcome"]] = float(p["prob"])

    # El mercado (cuota de cierre) se evalua sobre EXACTAMENTE los partidos que
    # el modelo tiene completos y con cuota, y con el mismo nombre que ya usa
    # la referencia del backtest. Es el techo del proyecto; sin el, 'log-loss
    # en vivo' es un numero suelto que solo se puede comparar con Elo, y Elo
    # no es el techo de nada. Solo existe para 1X2: para tarjetas la referencia
    # es la base, que 04_predict emite como un modelo mas (base-freq-v1).
    def market_ref(market, r):
        """La probabilidad del mercado para ese mercado, o None. Solo 1X2 y
        goles 2.5 tienen cuota en la fuente."""
        if market == MARKET_1X2 and r.get("market_h"):
            return {"H": float(r["market_h"]), "D": float(r["market_d"]),
                    "A": float(r["market_a"])}
        if market == "GOLES_OU25" and r.get("market_o25"):
            return {"OVER": float(r["market_o25"]), "UNDER": float(r["market_u25"])}
        return None

    for (model_version, market), matches in list(by_key.items()):
        if model_version in (MARKET_REFERENCE, BASE_MODEL_VERSION):
            continue
        n_out = len(OUTCOMES) if market == MARKET_1X2 else len(live_markets.OUTCOMES_OU)
        mk = {}
        for mid, m in matches.items():
            ref = market_ref(market, rows[mid])
            if len(m["probs"]) == n_out and ref:
                mk[mid] = {"probs": ref, "actual": m["actual"]}
        if mk:
            by_key[(MARKET_REFERENCE, market)] = mk

    out = []
    for (model_version, market), matches in by_key.items():
        outcomes = OUTCOMES if market == MARKET_1X2 else live_markets.OUTCOMES_OU
        pairs = [(m["probs"], m["actual"]) for m in matches.values()
                 if len(m["probs"]) == len(outcomes)]
        if not pairs:
            continue
        res = scoring.evaluate([p for p, _ in pairs], [a for _, a in pairs],
                               outcomes=outcomes)
        out.append({"model_version": model_version, "market": market,
                    "eval_set": "live", "n_matches": res["n_matches"],
                    "log_loss": f"{res['log_loss']:.6f}",
                    "brier": f"{res['brier']:.6f}",
                    "accuracy": f"{res['accuracy']:.6f}",
                    "computed_at": ledger.now_iso()})
    return out, by_key


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
    print(f"\n{'TRACK RECORD EN VIVO':40}{'mercado':>15}{'log-loss':>10}"
          f"{'Brier':>9}{'acc':>8}{'n':>6}")
    print("  " + "-" * 86)
    for m in sorted(metrics, key=lambda r: (r["market"], float(r["log_loss"]))):
        print(f"  {m['model_version']:38}{m['market']:>15}"
              f"{float(m['log_loss']):>10.4f}"
              f"{float(m['brier']):>9.4f}{float(m['accuracy'])*100:>7.1f}%"
              f"{m['n_matches']:>6}")

    # Contexto: sin una referencia, un log-loss suelto no dice nada. Para el
    # 1X2 la que importa es el mercado sobre ESTOS partidos; para tarjetas, la
    # frecuencia base (no hay cuota). Elo del backtest queda como segunda
    # referencia del 1X2.
    live = {(m["model_version"], m["market"]): m for m in metrics}
    print()
    for (mv, mk), m in sorted(live.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if mv in (MARKET_REFERENCE, BASE_MODEL_VERSION):
            continue
        for ref_name, ref_label in ((MARKET_REFERENCE, "el mercado"),
                                    (BASE_MODEL_VERSION, "la base")):
            ref = live.get((ref_name, mk))
            if not ref:
                continue
            d = float(m["log_loss"]) - float(ref["log_loss"])
            print(f"  {mk:14} {mv} contra {ref_label}, mismos "
                  f"{ref['n_matches']} partidos: {d:+.4f} "
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
