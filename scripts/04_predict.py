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

from marcador import (backtest, db, dixon_coles as dc, market_pre,  # noqa: E402
                      fixtures, ingest, ledger, live_markets, promotion,
                      recalibration)
from marcador.backtest import ModelConfig                   # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES, register_model  # noqa: E402
from marcador.config import (BASE_MODEL_VERSION, CURRENT_SEASON,  # noqa: E402
                             FIXTURES_LOOKAHEAD_DAYS, LEAGUES, LIVE_MARKETS,
                             PRODUCTION_REG, PRODUCTION_USE_RHO, PRODUCTION_XI,
                             league_label)
from marcador.markets import BY_KEY                         # noqa: E402


def refresh_data(con):
    """Re-baja SOLO la temporada en curso de cada liga y los proximos partidos.

    Dos fuentes distintas a proposito: el historico y los resultados siguen
    viniendo de football-data.co.uk (cuotas de cierre); los proximos partidos
    vienen del proveedor de fixtures.py, que traduce los nombres al vocabulario
    de la primera antes de escribir nada.
    """
    n_played = 0
    for league in LEAGUES:
        path = ingest.download_season(CURRENT_SEASON, league, force=True)
        n_played += ingest.upsert_matches(
            con, ingest.rows_from_csv(path, league, CURRENT_SEASON))
    snap = fixtures.download_all()
    n_new = sum(ingest.upsert_fixtures(con, fixtures.fixture_rows(snap, lg))
                for lg in LEAGUES)
    return n_played, n_new, snap


def report_source(snap, today, dry=False):
    """El estado de la fuente de fixtures, SIEMPRE, haya partidos o no.

    Lo imprime y lo deja en ledger/source_health.csv, una fila por liga. El
    log de Actions expira; el ledger no. Devuelve True si algo impide confiar
    en que 'no hay partidos' signifique que no hay jornada: una liga que no
    bajo, o equipos sin alias.
    """
    salud = fixtures.health(snap, today)
    stamp = ledger.now_iso()
    unknown_by_lg = {}
    for lg, name in snap.unknown:
        unknown_by_lg.setdefault(lg, []).append(name)
    health_rows = []
    for lg in LEAGUES:
        h = salud.get(lg, {})
        health_rows.append({
            "checked_at": stamp, "league": lg,
            "upcoming": h.get("upcoming", ""), "unconfirmed": h.get("unconfirmed", ""),
            "file_last_date": h.get("last") or "",
            "file_age_hours": (f"{h['age_hours']:.1f}" if h.get("age_hours") is not None else ""),
            "error": snap.errors.get(lg, ""),
            "unknown_teams": "|".join(unknown_by_lg.get(lg, []))})
    if not dry:
        ledger.append_health(health_rows)
    print(f"Fuente de fixtures: fixturedownload.com · {len(snap.files)} de "
          f"{len(LEAGUES)} ligas bajadas · ventana de {FIXTURES_LOOKAHEAD_DAYS} dias")
    for lg in LEAGUES:
        etiqueta = league_label(lg)
        if lg in snap.errors:
            print(f"  {etiqueta:16} ERROR al bajar: {snap.errors[lg]}")
            continue
        h = salud[lg]
        edad = f"{h['age_hours']:.0f} h" if h["age_hours"] is not None else "?"
        sin = (f", {h['unconfirmed']} SIN HORA" if h["unconfirmed"] else "")
        print(f"  {etiqueta:16} {h['upcoming']:2} partidos en la ventana{sin}"
              f" · archivo hasta {h['last']} · escrito hace {edad}")
    if snap.unknown:
        print("  AVISO: nombres que la tabla de alias no reconoce. Sus partidos "
              "NO se predijeron")
        print("  (se salta antes que adivinar: un id equivocado es una "
              "prediccion huerfana e inmutable):")
        for lg, name in snap.unknown:
            print(f"    {lg}: {name!r}  -> agregar a src/marcador/aliases.py")
        print("  05_score.py los va a reportar en missed.csv cuando se jueguen.")
    return bool(snap.errors) or bool(snap.unknown)


def record_market_pre(window_ids, dry=False):
    """Baja las cuotas pre-partido y deja en el ledger las que cambiaron.

    Solo para partidos cuyo kickoff no ha pasado (los de la ventana): asi
    'pre' es pre de verdad. La fuente es la anterior de fixtures, que se
    congela a ratos; un partido sin fila aqui no pierde nada mas que esta
    columna de contexto.
    """
    try:
        snap = market_pre.fetch()
        rows = market_pre.ledger_rows(market_pre.rows(snap), snap, window_ids,
                                      fetched_at=ledger.now_iso())
    except Exception as exc:                            # noqa: BLE001
        print(f"Cuotas pre-partido: no se pudieron bajar ({str(exc)[:60]}). "
              "Se sigue sin ellas.")
        return 0
    n = 0 if dry else ledger.append_market_pre(rows)
    print(f"Cuotas pre-partido: {len(rows)} de {len(window_ids)} partidos en "
          f"la ventana traen cuota · archivo {snap.describe()} · "
          f"{n} filas nuevas en ledger/market_pre.csv")
    return n


def pending_fixtures(con, today, league, now_utc=None,
                     horizon_days=FIXTURES_LOOKAHEAD_DAYS):
    """Partidos de una liga sin resultado, de hoy hasta `horizon_days` adelante,
    cuyo kickoff no haya pasado.

    Los tres filtros son la regla 3 aplicada de tres formas:

    · Fecha pasada sin resultado no es un partido por jugar, es uno cuyo
      resultado no han publicado (o se aplazo). Predecirlo seria emitir
      despues del kickoff.
    · Kickoff pasado, mismo caso pero con la hora, que desde el 2026-09-10
      esta disponible en UTC real para lo que viene de fixtures.py.
    · Y el TOPE hacia adelante, que hasta ese dia no hacia falta porque la
      fuente solo mostraba tres dias: con la temporada completa a la vista,
      sin tope se predeciria un partido de mayo con el modelo de septiembre —
      y como una prediccion escrita no se reemplaza, esa seria la que quedaria.
      Cada partido se predice lo mas cerca posible del kickoff, no lo mas
      pronto posible.
    """
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    horizon = today + dt.timedelta(days=horizon_days)
    return con.execute(
        """SELECT match_id, match_date, home_team, away_team, kickoff_utc
           FROM matches
           WHERE league = ? AND ftr IS NULL
             AND match_date >= ? AND match_date <= ?
             AND (kickoff_utc IS NULL OR kickoff_utc > ?)
           ORDER BY match_date, home_team""",
        (league, today.isoformat(), horizon.isoformat(),
         now_utc.strftime("%Y-%m-%dT%H:%M"))).fetchall()


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

    n_played, n_new, snap = refresh_data(con)
    print(f"Datos: {n_played} partidos de la temporada en curso · "
          f"{n_new} fixtures nuevos")
    source_problem = report_source(snap, today, dry=dry)

    champ = promotion.read_champion()
    cfg = champ["config"] if champ else ModelConfig(
        xi=PRODUCTION_XI, reg=PRODUCTION_REG, use_rho=PRODUCTION_USE_RHO)
    spec = champ.get("recalibration") if champ else None
    version = champ["raw"]["model_version"] if champ else cfg.slug()

    # Cada mercado lleva su propia lista de pendientes, porque cada uno firma
    # con su propio model_version: un partido puede tener el 1X2 emitido y las
    # tarjetas no (los 43 del primer lote, por ejemplo).
    ou_version = {k: live_markets.market_version(cfg, k) for k in LIVE_MARKETS}
    todo_by_league, in_window = {}, []
    todo_ou = {k: {} for k in LIVE_MARKETS}       # mercado -> liga -> fixtures
    already_1x2 = ledger.predicted_matches(version)
    already_ou = {k: ledger.predicted_matches(v) for k, v in ou_version.items()}
    for league in LEAGUES:
        pend = pending_fixtures(con, today, league)
        in_window += pend
        todo = [f for f in pend if f["match_id"] not in already_1x2]
        if todo:
            todo_by_league[league] = todo
        for k in LIVE_MARKETS:
            t = [f for f in pend if f["match_id"] not in already_ou[k]]
            if t:
                todo_ou[k][league] = t

    # La hora de TODO lo que esta en la ventana, predicho o no todavia. Va a un
    # archivo aparte porque cambia (aplazamientos) y las predicciones no. Se
    # escribe antes del 'nada que hacer' a proposito: un partido ya predicho
    # cuya hora se movio tiene que quedar registrado aunque no haya nada nuevo
    # que predecir.
    if in_window and not dry:
        stamp = ledger.now_iso()
        n_fx = ledger.upsert_fixtures([
            {"match_id": f["match_id"], "match_date": f["match_date"],
             "kickoff_utc": f["kickoff_utc"], "home_team": f["home_team"],
             "away_team": f["away_team"], "updated_at": stamp}
            for f in in_window])
        if n_fx:
            print(f"Horas de partido: {n_fx} actualizadas en ledger/fixtures.csv")

    # La opinion del mercado ANTES del partido, para todo lo que esta en la
    # ventana. Va antes del 'nada que hacer' por la misma razon que las horas:
    # la linea se mueve aunque no haya nada nuevo que predecir. Un fallo aqui
    # no puede frenar las predicciones: es un dato de contexto, no del modelo.
    if in_window:
        record_market_pre({f["match_id"] for f in in_window}, dry=dry)

    if not todo_by_league and not any(todo_ou.values()):
        # Los dos casos se leian igual hasta el 2026-09-10, y no son el mismo:
        # uno es el sistema funcionando y el otro es el sistema perdiendo
        # jornadas en silencio. Que un partido llegue a jugarse sin prediccion
        # lo verifica ademas 05_score.py, pero eso se sabe DESPUES del kickoff;
        # esto se sabe antes.
        if source_problem:
            print("Sin partidos que predecir, pero la fuente tuvo problemas "
                  "(ver arriba): NO se puede")
            print("concluir que no haya jornada.")
        else:
            print("No hay partidos por jugar sin prediccion, y la fuente "
                  "esta completa:")
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

    # --- Mercados over/under: tarjetas y goles 2.5 ---------------------------
    # Mismo motor, otra columna (F5). Sin recalibracion, encogido hacia la
    # frecuencia base, y la base se emite como un modelo mas: para tarjetas es
    # la unica referencia que hay; para goles 2.5 ademas existe la cuota de
    # cierre, que 05_score guarda con el resultado.
    ou_rows = {k: [] for k in LIVE_MARKETS}
    for key, by_league in todo_ou.items():
        lines = LIVE_MARKETS[key]["lines"]
        label = BY_KEY[key].label.lower()
        for league, todo in by_league.items():
            rows, info = live_markets.predict(con, league, key, todo, cfg, now)
            if info is None:
                print(f"\n  {league_label(league)}: sin historial de {label}, "
                      f"no se emite este mercado.")
                continue
            ou_rows[key] += rows
            print(f"\n  {league_label(league)} — {label} "
                  f"(base: {', '.join(f'>{l} {info['base'][l]:.0%}' for l in lines)})")
            print(f"  {'partido':44}{'fecha':>12}"
                  + "".join(f"{'>'+str(l):>8}" for l in lines))
            by_match = {}
            for r in rows:
                if r["model_version"] == info["version"] and r["outcome"] == "OVER":
                    by_match.setdefault(r["match_id"], {})[r["market"]] = float(r["prob"])
            for f in todo:
                p = by_match.get(f["match_id"])
                if not p:
                    continue
                print(f"  {f['home_team'] + ' vs ' + f['away_team']:44}"
                      f"{f['match_date']:>12}"
                      + "".join(f"{p[live_markets.market_code(BY_KEY[key], l)]*100:>7.1f}%"
                                for l in lines))
            for f in info["skipped"]:
                print(f"  {f['home_team'] + ' vs ' + f['away_team']:44}"
                      f"{f['match_date']:>12}   (equipo sin historial, no se emite)")
        new_rows += ou_rows[key]

    if dry:
        print("\n--dry-run: no se escribio nada.")
        return 0

    for key, rows in ou_rows.items():
        if not rows:
            continue
        register_model(con, ou_version[key], "dixon-coles",
                       params={**cfg.to_dict(), "use_rho": BY_KEY[key].use_rho,
                               "shrink": LIVE_MARKETS[key]},
                       notes=f"{BY_KEY[key].label} en vivo; w de 12_markets_multi (5 ligas)")
    if any(ou_rows.values()):
        register_model(con, BASE_MODEL_VERSION, "baseline",
                       params={"what": "frecuencia de OVER en la liga antes del partido"},
                       notes="referencia para mercados over/under")

    # La base del runner nace vacia en cada corrida, y `predictions` exige que
    # el modelo exista en `model_versions`. Solo 02 y 03 registraban, y esos no
    # corren en el loop. Estuvo latente hasta la primera corrida con partidos
    # reales (2026-09-10): en seco no se inserta, y hasta ese dia nunca hubo
    # nada que insertar. Idempotente: registrar dos veces no duplica.
    register_model(con, version, "dixon-coles",
                   params={**cfg.to_dict(), "recalibration": spec},
                   notes="modelo en produccion, registrado por 04_predict.py")

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
    n_1x2 = sum(1 for r in new_rows if r["market"] == MARKET_1X2) // len(OUTCOMES)
    por_mercado = ", ".join(
        f"{len({r['match_id'] for r in rows})} de {BY_KEY[k].label.lower()}"
        for k, rows in ou_rows.items())
    print(f"\n{n} filas nuevas en el ledger: {n_1x2} partidos de 1X2, "
          f"{por_mercado}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
