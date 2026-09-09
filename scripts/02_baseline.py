#!/usr/bin/env python3
"""F1 · paso 2 — Genera las predicciones baseline y calcula el marcador.

    python3 scripts/02_baseline.py

Aquí no hay machine learning, y esa es la idea: lo que se está probando es el
sistema de medición, no el modelo. Se generan predicciones walk-forward de tres
referencias y se miden con log-loss, Brier y calibración.

El walk-forward tiene un detalle que arruina el ejercicio si se hace mal: los
partidos se procesan AGRUPADOS POR FECHA. Se predicen todos los de un mismo día
antes de actualizar con cualquiera de ellos. Si se procesaran uno por uno, el
segundo partido de un sábado usaría el resultado del primero, que a esa hora
todavía no se había jugado. Es data leakage de unas horas, invisible en el
código y suficiente para inflar el resultado.
"""
import datetime as dt
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import baseline, db, scoring                 # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES         # noqa: E402
from marcador.config import LEAGUE, SEASONS                # noqa: E402

# La primera temporada no se puede predecir con frecuencia base: no hay pasado.
# Se usa entera como entrenamiento inicial.
WARMUP_SEASONS = 1


def load_matches(con):
    return con.execute(
        """SELECT * FROM matches
           WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (LEAGUE,)).fetchall()


def day_before(date_iso):
    return (dt.date.fromisoformat(date_iso) - dt.timedelta(days=1)).isoformat()


def save_predictions(con, rows_probs, model_version, mode="backtest"):
    """Escribe en la tabla inmutable. Si una fila ya existe, se deja como está:
    reescribirla es exactamente lo que el proyecto prohíbe."""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    n = 0
    for match_id, probs, cutoff in rows_probs:
        for outcome in OUTCOMES:
            con.execute(
                """INSERT INTO predictions (match_id, model_version, market,
                       outcome, prob, mode, info_cutoff, created_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT (match_id, model_version, market, outcome)
                   DO NOTHING""",
                (match_id, model_version, MARKET_1X2, outcome,
                 probs[outcome], mode, cutoff, now))
        n += 1
    con.commit()
    return n


def run_base_rate(con, matches):
    """Walk-forward: la frecuencia se recalcula con todo lo anterior a la
    temporada que se está prediciendo, y no se toca durante esa temporada."""
    out = []
    for season in SEASONS[WARMUP_SEASONS:]:
        past = [m for m in matches if m["season"] < season]
        current = [m for m in matches if m["season"] == season]
        if not past or not current:
            continue
        probs = baseline.base_rate(past)
        cutoff = max(m["match_date"] for m in past)
        for m in current:
            out.append((m["match_id"], probs, cutoff))
    return out


def run_elo(con, matches):
    """Elo recorre la historia en orden y se actualiza solo con el pasado.

    Las primeras temporadas se usan como calentamiento: los ratings arrancan
    todos iguales en 1500 y necesitan partidos para separarse. Predecir con
    ratings sin calentar mediría el arranque, no el modelo.
    """
    elo = baseline.Elo()
    warmup_seasons = set(SEASONS[:WARMUP_SEASONS])
    out = []
    # groupby por fecha: se predice todo el día, después se actualiza todo el
    # día. Ver la nota del docstring del módulo.
    for date_iso, group in itertools.groupby(matches, key=lambda m: m["match_date"]):
        group = list(group)
        for m in group:
            if m["season"] not in warmup_seasons:
                out.append((m["match_id"], elo.predict(m["home_team"], m["away_team"]),
                            day_before(date_iso)))
        for m in group:
            elo.update(m["home_team"], m["away_team"], m["ftr"])
    return out


def run_market(con, matches):
    """El mercado no se entrena: la cuota de cierre ya es una predicción."""
    out = []
    for m in matches:
        probs = baseline.market_probs(m)
        if probs:
            out.append((m["match_id"], probs, day_before(m["match_date"])))
    return out


def score_model(con, model_version, matches_by_id):
    """Lee de vuelta lo que quedó guardado y lo mide.

    Se mide leyendo la tabla, no la variable en memoria. Es a propósito: lo que
    se evalúa tiene que ser lo que quedó registrado, no lo que el script creyó
    haber calculado.
    """
    rows = con.execute(
        """SELECT match_id, outcome, prob FROM predictions
           WHERE model_version = ? AND market = ?""",
        (model_version, MARKET_1X2)).fetchall()
    by_match = {}
    for r in rows:
        by_match.setdefault(r["match_id"], {})[r["outcome"]] = r["prob"]

    preds, actual = [], []
    for match_id, probs in by_match.items():
        if len(probs) != 3:
            continue
        preds.append(probs)
        actual.append(matches_by_id[match_id]["ftr"])

    res = scoring.evaluate(preds, actual)
    scoring.save_metrics(con, model_version, MARKET_1X2, "walkforward", res)
    scoring.save_calibration(con, model_version, MARKET_1X2, "walkforward",
                             scoring.calibration_bins(preds, actual))
    return res


def main():
    con = db.init_db()
    matches = load_matches(con)
    if not matches:
        sys.exit("No hay partidos. Corre primero: python3 scripts/01_ingest.py")
    by_id = {m["match_id"]: m for m in matches}
    print(f"{len(matches)} partidos cargados ({matches[0]['match_date']} "
          f"a {matches[-1]['match_date']})\n")

    specs = [
        ("baseline-freq-v1", "baseline", run_base_rate,
         "Frecuencia base historica, recalculada por temporada"),
        ("baseline-elo-v1", "elo", run_elo,
         "Elo k=20 home_adv=60 draw_share=0.26"),
        ("market-close-v1", "market", run_market,
         "Cuota de cierre Pinnacle sin margen"),
    ]

    results = {}
    for version, family, fn, notes in specs:
        baseline.register_model(con, version, family, notes=notes)
        n = save_predictions(con, fn(con, matches), version)
        results[version] = score_model(con, version, by_id)
        print(f"  {version:20} {n:>4} partidos predichos")

    print(f"\n{'MARCADOR':20} {'log-loss':>10} {'Brier':>10} {'accuracy':>10}"
          f"  {'partidos':>9}")
    print("  " + "-" * 63)
    for version, _, _, _ in specs:
        r = results[version]
        print(f"  {version:18} {r['log_loss']:>10.4f} {r['brier']:>10.4f} "
              f"{r['accuracy']*100:>9.1f}% {r['n_matches']:>9}")

    freq = results["baseline-freq-v1"]["log_loss"]
    mkt = results["market-close-v1"]["log_loss"]
    print(f"\n  Espacio entre la frecuencia base y el mercado: "
          f"{freq - mkt:.4f} de log-loss.")
    print(f"  Ahi es donde tiene que caber el modelo de la F2.")


if __name__ == "__main__":
    main()
