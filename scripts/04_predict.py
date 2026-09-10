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

import numpy as np                                        # noqa: E402

from marcador import (backtest, db, dixon_coles as dc,     # noqa: E402
                      ingest, ledger, promotion, recalibration)
from marcador.backtest import ModelConfig                   # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES          # noqa: E402
from marcador.config import (CURRENT_SEASON, LEAGUES,       # noqa: E402
                             PRODUCTION_REG, PRODUCTION_USE_RHO,
                             PRODUCTION_XI, league_label)


def refresh_data(con):
    """Re-baja SOLO la temporada en curso de cada liga y los proximos partidos."""
    n_played = 0
    for league in LEAGUES:
        path = ingest.download_season(CURRENT_SEASON, league, force=True)
        n_played += ingest.upsert_matches(
            con, ingest.rows_from_csv(path, league, CURRENT_SEASON))
    fx = ingest.download_fixtures()
    n_new = sum(ingest.upsert_fixtures(con, ingest.fixture_rows(fx.path, lg))
                for lg in LEAGUES)
    return n_played, n_new, fx


def pending_fixtures(con, today, league):
    """Partidos de una liga sin resultado y con fecha de hoy en adelante.

    El filtro por fecha importa: un partido sin resultado y con fecha pasada no
    es un partido por jugar, es uno cuyo resultado todavia no publicaron (o que
    se aplazo). Predecirlo seria emitir una prediccion despues del kickoff.
    """
    return con.execute(
        """SELECT match_id, match_date, home_team, away_team, kickoff_utc
           FROM matches
           WHERE league = ? AND ftr IS NULL AND match_date >= ?
           ORDER BY match_date, home_team""",
        (league, today.isoformat())).fetchall()


def train_recalibration(con, cfg, spec):
    """Ajusta la capa de recalibracion con historia, si el campeon la lleva.

    Devuelve (pesos, media, desviacion) o None. Se entrena una sola vez por
    corrida y sirve para las cinco ligas: las features son diferencias de
    forma, comparables entre competiciones, y las diferencias de nivel entre
    ligas ya las absorbe el offset, que es la prediccion del modelo de esa liga.
    """
    if not spec:
        return None
    seasons = spec["train_seasons"]
    ids, y, probs, feats = [], [], {}, {}
    yi = {o: i for i, o in enumerate(recalibration.OUTCOMES)}
    for league in LEAGUES:
        rows = con.execute(
            """SELECT match_id, match_date, season, home_team, away_team, ftr,
                      fthg, ftag, hs, "as", hst, ast, hc, ac
               FROM matches WHERE league = ? AND ftr IS NOT NULL
               ORDER BY match_date, home_team""", (league,)).fetchall()
        feats.update(recalibration.rolling_features(rows, spec["window"]))
        by_id = {r["match_id"]: r for r in rows}
        ms = backtest.load_matches(con, league)
        preds, _, _ = backtest.walk_forward(ms, seasons, cfg)
        for mid, p, _ in preds:
            probs[mid] = p
            ids.append(mid)
            y.append(yi[by_id[mid]["ftr"]])
    if not ids:
        return None
    X, offset, mu, sd = recalibration.design_matrix(ids, probs, feats)
    b = recalibration.fit(X, offset, np.array(y), spec["lam"])
    return b, mu, sd, feats, spec


def apply_recalibration(layer, match_id, probs, feats_now):
    b, mu, sd, _, _ = layer
    X, offset, _, _ = recalibration.design_matrix(
        [match_id], {match_id: probs}, {match_id: feats_now}, mu, sd)
    out = recalibration.predict(b, X, offset)[0]
    return dict(zip(recalibration.OUTCOMES, out))


def main():
    dry = "--dry-run" in sys.argv
    today = dt.date.today()
    con = db.init_db()

    n_played, n_new, fx = refresh_data(con)
    print(f"Datos: {n_played} partidos de la temporada en curso · "
          f"{n_new} fixtures nuevos")

    # El estado de la fuente se reporta SIEMPRE, haya partidos o no. Es la
    # unica forma de que el log distinga "no juega nadie" de "la foto de la
    # fuente lleva dias congelada" (ver FIXTURES_STALE_HOURS en config).
    resumen = ingest.fixtures_summary(fx.path)
    ligas = ", ".join(f"{k}:{v}" for k, v in sorted(resumen["leagues"].items()))
    print(f"Fuente de fixtures: {fx.describe()} · {resumen['n']} partidos"
          + (f" del {resumen['first']} al {resumen['last']}"
             if resumen["first"] else ""))
    print(f"  ligas en el archivo: {ligas or '(ninguna)'}")
    nuestras = [lg for lg in LEAGUES if lg in resumen["leagues"]]
    if not nuestras:
        print(f"  NINGUNA de las nuestras ({', '.join(LEAGUES)}) esta en la foto.")
    if fx.is_stale:
        edad = (f"{fx.age_hours:.0f} h" if fx.age_hours is not None
                else "un tiempo que la fuente no declara")
        print(f"  AVISO: la foto lleva {edad} sin regenerarse. Mientras no la "
              f"regenere,")
        print(f"  ninguna jornada nueva puede entrar por mucho que corra "
              f"este job.")

    champ = promotion.read_champion()
    cfg = champ["config"] if champ else ModelConfig(
        xi=PRODUCTION_XI, reg=PRODUCTION_REG, use_rho=PRODUCTION_USE_RHO)
    spec = champ.get("recalibration") if champ else None
    version = champ["raw"]["model_version"] if champ else cfg.slug()

    todo_by_league = {}
    for league in LEAGUES:
        pend = pending_fixtures(con, today, league)
        already = ledger.predicted_matches(version)
        todo = [f for f in pend if f["match_id"] not in already]
        if todo:
            todo_by_league[league] = todo
    if not todo_by_league:
        # Los dos casos se leian igual hasta el 2026-09-10, y no son el mismo:
        # uno es el sistema funcionando y el otro es el sistema perdiendo
        # jornadas en silencio. Que un partido llegue a jugarse sin prediccion
        # lo verifica ademas 05_score.py, pero eso se sabe DESPUES del kickoff;
        # esto se sabe antes.
        if fx.is_stale:
            print("Sin partidos que predecir, y la foto de la fuente esta "
                  "rancia: NO se puede")
            print("concluir que no haya jornada. Revisar si la fuente se "
                  "destrabo.")
        else:
            print("No hay partidos por jugar sin prediccion, y la foto de la "
                  "fuente esta al dia:")
            print("no hay jornada en la ventana. Nada que hacer.")
        return 0

    layer = train_recalibration(con, cfg, spec) if spec else None
    print(f"Modelo en produccion: {version}"
          + ("  (con capa de recalibracion)" if layer else ""))

    now = ledger.now_iso()
    new_rows = []
    for league, todo in todo_by_league.items():
        first = dt.date.fromisoformat(min(f["match_date"] for f in todo))
        rows = con.execute(
            """SELECT match_date, home_team, away_team, fthg, ftag FROM matches
               WHERE league = ? AND ftr IS NOT NULL AND match_date < ?
               ORDER BY match_date""", (league, first.isoformat())).fetchall()
        train = [{"date": dt.date.fromisoformat(r["match_date"]),
                  "home": r["home_team"], "away": r["away_team"],
                  "hg": r["fthg"], "ag": r["ftag"]} for r in rows]
        if not train:
            continue
        fit = dc.fit(train, first, xi=cfg.xi, use_rho=cfg.use_rho, reg=cfg.reg)
        cutoff = max(m["date"] for m in train).isoformat()

        # Features de forma calculadas con TODO lo jugado antes del fixture.
        hist_rows = con.execute(
            """SELECT match_id, match_date, season, home_team, away_team, ftr,
                      fthg, ftag, hs, "as", hst, ast, hc, ac
               FROM matches WHERE league = ? AND (ftr IS NOT NULL OR match_id IN
                     (%s)) ORDER BY match_date, home_team"""
            % ",".join("?" * len(todo)),
            [league] + [f["match_id"] for f in todo]).fetchall()
        feats_all = recalibration.rolling_features(
            hist_rows, spec["window"] if spec else 10)

        print(f"\n  {league_label(league)}")
        print(f"  {'partido':44}{'fecha':>12}{'H':>7}{'D':>7}{'A':>7}")
        for f in todo:
            probs = fit.probs_1x2(f["home_team"], f["away_team"])
            if layer and f["match_id"] in feats_all:
                probs = apply_recalibration(layer, f["match_id"], probs,
                                            feats_all[f["match_id"]])
            print(f"  {f['home_team'] + ' vs ' + f['away_team']:44}"
                  f"{f['match_date']:>12}{probs['H']*100:>6.1f}%"
                  f"{probs['D']*100:>6.1f}%{probs['A']*100:>6.1f}%")
            for o in OUTCOMES:
                new_rows.append({
                    "match_id": f["match_id"], "match_date": f["match_date"],
                    "home_team": f["home_team"], "away_team": f["away_team"],
                    "model_version": version, "market": MARKET_1X2,
                    "outcome": o, "prob": f"{probs[o]:.6f}", "mode": "live",
                    "info_cutoff": cutoff, "created_at": now})

    if dry:
        print("\n--dry-run: no se escribio nada.")
        return 0

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
