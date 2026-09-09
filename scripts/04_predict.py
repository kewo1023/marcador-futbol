#!/usr/bin/env python3
"""F3 · Emite predicciones de los proximos partidos y las guarda en el ledger.

    ./.venv/bin/python scripts/04_predict.py [--dry-run]

Corre a diario en GitHub Actions. Es la mitad del ciclo que la fase 3 automatiza:
esta escribe antes del partido, y 05_score.py mide despues.

LO QUE NUNCA HACE: reescribir una prediccion ya emitida. Si un partido ya
tiene prediccion en el ledger, se salta. El ledger levanta una excepcion si
alguien intenta escribir una probabilidad distinta para la misma clave.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import db, dixon_coles as dc, ingest, ledger  # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES          # noqa: E402
from marcador.config import (CURRENT_SEASON, LEAGUE, PRODUCTION_MODEL,  # noqa: E402
                             PRODUCTION_REG, PRODUCTION_USE_RHO, PRODUCTION_XI)


def refresh_data(con):
    """Re-baja SOLO la temporada en curso (las cerradas ya no cambian) y los
    proximos partidos."""
    path = ingest.download_season(CURRENT_SEASON, force=True)
    n_played = ingest.upsert_matches(
        con, ingest.rows_from_csv(path, LEAGUE, CURRENT_SEASON))
    fx = ingest.download_fixtures()
    n_new = ingest.upsert_fixtures(con, ingest.fixture_rows(fx, LEAGUE))
    return n_played, n_new


def pending_fixtures(con, today):
    """Partidos de nuestra liga sin resultado y con fecha de hoy en adelante.

    El filtro por fecha importa: un partido sin resultado y con fecha pasada no
    es un partido por jugar, es un partido cuyo resultado todavia no publicaron
    (o que se aplazo). Predecirlo seria emitir una prediccion despues del
    kickoff, que es exactamente lo que el proyecto prohibe.
    """
    return con.execute(
        """SELECT match_id, match_date, home_team, away_team, kickoff_utc
           FROM matches
           WHERE league = ? AND ftr IS NULL AND match_date >= ?
           ORDER BY match_date, home_team""", (LEAGUE, today.isoformat())).fetchall()


def main():
    dry = "--dry-run" in sys.argv
    today = dt.date.today()
    con = db.init_db()

    n_played, n_new = refresh_data(con)
    print(f"Datos: {n_played} partidos de la temporada en curso · "
          f"{n_new} fixtures nuevos")

    fixtures = pending_fixtures(con, today)
    if not fixtures:
        # Caso normal, no error: el archivo de fixtures cubre pocos dias y en
        # parones de seleccion puede no traer ninguno de esta liga.
        print("No hay partidos por jugar en la ventana disponible. Nada que hacer.")
        return 0

    already = ledger.predicted_matches(PRODUCTION_MODEL)
    todo = [f for f in fixtures if f["match_id"] not in already]
    print(f"{len(fixtures)} partidos por jugar · {len(todo)} sin prediccion")
    if not todo:
        print("Todos ya tienen prediccion. El ledger no se toca.")
        return 0

    # Un solo ajuste para toda la tanda: los fixtures caben en pocos dias y en
    # una semana de futbol la liga no cambia lo suficiente para justificar
    # reajustar por partido.
    first = dt.date.fromisoformat(min(f["match_date"] for f in todo))
    rows = con.execute(
        """SELECT match_date, home_team, away_team, fthg, ftag FROM matches
           WHERE league = ? AND ftr IS NOT NULL AND match_date < ?
           ORDER BY match_date""", (LEAGUE, first.isoformat())).fetchall()
    train = [{"date": dt.date.fromisoformat(r["match_date"]), "home": r["home_team"],
              "away": r["away_team"], "hg": r["fthg"], "ag": r["ftag"]} for r in rows]

    fit = dc.fit(train, first, xi=PRODUCTION_XI, use_rho=PRODUCTION_USE_RHO,
                 reg=PRODUCTION_REG)
    cutoff = max(m["date"] for m in train).isoformat()
    print(f"Modelo {PRODUCTION_MODEL} ajustado con {fit.n_matches} partidos "
          f"hasta {cutoff} (converge={fit.converged})\n")

    now = ledger.now_iso()
    new_rows, preview = [], []
    for f in todo:
        probs = fit.probs_1x2(f["home_team"], f["away_team"])
        unknown = not (fit.knows(f["home_team"]) and fit.knows(f["away_team"]))
        preview.append((f, probs, unknown))
        for o in OUTCOMES:
            new_rows.append({
                "match_id": f["match_id"], "match_date": f["match_date"],
                "home_team": f["home_team"], "away_team": f["away_team"],
                "model_version": PRODUCTION_MODEL, "market": MARKET_1X2,
                "outcome": o, "prob": f"{probs[o]:.6f}", "mode": "live",
                "info_cutoff": cutoff, "created_at": now,
            })

    print(f"  {'partido':44}{'fecha':>12}{'H':>7}{'D':>7}{'A':>7}")
    for f, p, unknown in preview:
        flag = "  (equipo sin historia)" if unknown else ""
        print(f"  {f['home_team'] + ' vs ' + f['away_team']:44}{f['match_date']:>12}"
              f"{p['H']*100:>6.1f}%{p['D']*100:>6.1f}%{p['A']*100:>6.1f}%{flag}")

    if dry:
        print("\n--dry-run: no se escribio nada.")
        return 0

    # A la base tambien, para que el trigger de no-leakage verifique cada fila.
    for r in new_rows:
        con.execute(
            """INSERT INTO predictions (match_id, model_version, market, outcome,
                   prob, mode, info_cutoff, created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (match_id, model_version, market, outcome) DO NOTHING""",
            (r["match_id"], r["model_version"], r["market"], r["outcome"],
             float(r["prob"]), r["mode"], r["info_cutoff"], r["created_at"]))
    con.commit()

    n = ledger.append_predictions(new_rows)
    print(f"\n{n} filas nuevas en el ledger ({n // len(OUTCOMES)} partidos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
