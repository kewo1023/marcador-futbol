#!/usr/bin/env python3
"""F2 · Motor Dixon-Coles con backtest walk-forward.

    ./.venv/bin/python scripts/03_dixon_coles.py

Construye tres modelos que se diferencian en UNA cosa cada uno, para poder
atribuir la mejora a la pieza que la produjo y no a "el modelo" en general:

    poisson          ataque x defensa x localia, todos los partidos pesan igual
    poisson+decay    lo mismo, pero los partidos viejos pesan menos
    dixon-coles      lo anterior + la correccion rho de los marcadores bajos

COMO SE PARTEN LAS TEMPORADAS
-----------------------------
    calentamiento   3 temporadas   solo entrenan, no se predicen
    validacion      3 temporadas   aqui se ELIGE xi
    prueba          5 temporadas   aqui se REPORTA, y nada se elige

Elegir xi mirando las mismas temporadas que luego se reportan infla el
resultado sin que se note. Es la version sutil del data leakage: no entra por
las features, entra por la decision de que hiperparametro usar.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import baseline, db, dixon_coles as dc, ledger, scoring  # noqa: E402
from marcador.baseline import MARKET_1X2, OUTCOMES             # noqa: E402
from marcador.config import LEAGUE, SEASONS                    # noqa: E402

WARMUP = SEASONS[:3]        # 2015/16 - 2017/18
VALIDATION = SEASONS[3:6]   # 2018/19 - 2020/21
TEST = SEASONS[6:]          # 2021/22 - 2025/26

# Cada cuantos dias se re-ajusta el modelo durante el backtest. Reajustar en
# cada partido seria mas fino y mucho mas lento; en una semana de futbol la
# liga casi no cambia, asi que el costo en precision es despreciable.
REFIT_DAYS = 7

XI_GRID = [0.001, 0.0015, 0.002, 0.003]
# reg empuja hacia el promedio de la liga a los equipos de los que hay poco.
REG_GRID = [0.0, 0.002, 0.005, 0.01, 0.02, 0.05]


def load(con):
    rows = con.execute(
        """SELECT match_id, match_date, season, home_team, away_team, fthg, ftag, ftr
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (LEAGUE,)).fetchall()
    return [{"id": r["match_id"], "date": dt.date.fromisoformat(r["match_date"]),
             "season": r["season"], "home": r["home_team"], "away": r["away_team"],
             "hg": r["fthg"], "ag": r["ftag"], "ftr": r["ftr"]} for r in rows]


def walk_forward(matches, target_seasons, xi, use_rho, reg=0.0, verbose=False):
    """Recorre el tiempo hacia adelante prediciendo solo con el pasado.

    Devuelve (predicciones, n_ajustes, n_equipos_desconocidos).
    """
    targets = [m for m in matches if m["season"] in target_seasons]
    if not targets:
        return [], 0, 0

    out, fit, last_fit, n_fits, unknown = [], None, None, 0, 0
    for m in targets:
        need_refit = (fit is None or last_fit is None
                      or (m["date"] - last_fit).days >= REFIT_DAYS)
        if need_refit:
            # Estrictamente ANTERIORES a la fecha del partido. El '<' es la
            # regla 4 entera; con '<=' se colaria el propio partido.
            train = [t for t in matches if t["date"] < m["date"]]
            if not train:
                continue
            fit = dc.fit(train, m["date"], xi=xi, use_rho=use_rho, reg=reg,
                         warm_start=fit)
            last_fit = m["date"]
            n_fits += 1
            # La fecha real del dato mas reciente que vio el modelo. Es lo que
            # se guarda como info_cutoff: siempre anterior al partido, que es
            # justo lo que el trigger de la base verifica.
            fit.last_data_date = max(t["date"] for t in train)

        if not fit.knows(m["home"]) or not fit.knows(m["away"]):
            unknown += 1
        out.append((m["id"], fit.probs_1x2(m["home"], m["away"]),
                    fit.last_data_date.isoformat()))
    return out, n_fits, unknown


def save(con, preds, model_version):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for match_id, probs, cutoff in preds:
        for o in OUTCOMES:
            con.execute(
                """INSERT INTO predictions (match_id, model_version, market,
                       outcome, prob, mode, info_cutoff, created_at)
                   VALUES (?,?,?,?,?,'backtest',?,?)
                   ON CONFLICT (match_id, model_version, market, outcome)
                   DO NOTHING""",
                (match_id, model_version, MARKET_1X2, o, probs[o], cutoff, now))
    con.commit()


def _val_log_loss(matches, xi, use_rho, reg):
    preds, _, _ = walk_forward(matches, VALIDATION, xi, use_rho, reg)
    by_match = {mid: p for mid, p, _ in preds}
    sel = [m for m in matches if m["season"] in VALIDATION and m["id"] in by_match]
    return scoring.log_loss([by_match[m["id"]] for m in sel],
                            [m["ftr"] for m in sel])


def tune(matches):
    """Elige xi y reg midiendo SOLO en las temporadas de validacion.

    xi  = que tan rapido olvida el modelo el pasado.
    reg = cuanto se empuja hacia el promedio de la liga a un equipo del que
          hay pocos datos. Es lo que impide que un recien ascendido reciba
          parametros extremos estimados sobre casi nada.
    """
    print("Eligiendo xi (decaimiento) y reg (regularizacion) en validacion.")
    print("  Cada celda es el log-loss walk-forward de esas 3 temporadas.\n")
    header = "".join(f"{r:>9}" for r in REG_GRID)
    print(f"  {'xi \\ reg':>10}{header}")
    best, best_ll = None, float("inf")
    for xi in XI_GRID:
        cells = []
        for reg in REG_GRID:
            ll = _val_log_loss(matches, xi, True, reg)
            cells.append(ll)
            if ll < best_ll:
                best, best_ll = (xi, reg), ll
        row = "".join(f"{c:>9.4f}" for c in cells)
        print(f"  {xi:>10}{row}")
    print(f"\n  Elegidos: xi={best[0]}  reg={best[1]}  (log-loss validacion {best_ll:.4f})\n")
    return best


def main():
    con = db.init_db()
    matches = load(con)
    print(f"{len(matches)} partidos.  calentamiento={len(WARMUP)} temporadas · "
          f"validacion={len(VALIDATION)} · prueba={len(TEST)}")
    print(f"Se reporta sobre {sum(1 for m in matches if m['season'] in TEST)} "
          f"partidos de prueba ({TEST[0]} a {TEST[-1]}).\n")

    xi, reg = tune(matches)
    tag = f"xi{int(round(xi*10000)):04d}-reg{int(round(reg*1000)):03d}"

    # Cada modelo agrega UNA pieza al anterior, para poder atribuir la mejora.
    specs = [
        ("poisson-v1", 0.0, False, 0.0,
         "Poisson: ataque x defensa x localia. Nada mas"),
        (f"poisson-decay-xi{int(round(xi*10000)):04d}-v1", xi, False, 0.0,
         f"+ decaimiento temporal xi={xi}"),
        (f"dixon-coles-xi{int(round(xi*10000)):04d}-v1", xi, True, 0.0,
         f"+ correccion rho de marcadores bajos"),
        (f"dixon-coles-{tag}-v1", xi, True, reg,
         f"+ regularizacion reg={reg} hacia el promedio de la liga"),
    ]

    print("Backtest walk-forward sobre validacion + prueba:")
    for version, xi_v, use_rho, reg_v, notes in specs:
        baseline.register_model(con, version, "dixon-coles",
                                params={"xi": xi_v, "use_rho": use_rho,
                                        "reg": reg_v, "refit_days": REFIT_DAYS},
                                notes=notes)
        preds, n_fits, unknown = walk_forward(matches, VALIDATION + TEST,
                                              xi_v, use_rho, reg_v)
        save(con, preds, version)
        print(f"  {version:32} {len(preds):>4} predicciones · "
              f"{n_fits} reajustes · {unknown} con equipo sin historia")

    # --- El marcador, solo sobre las temporadas de prueba --------------------
    all_models = ["baseline-freq-v1", "baseline-elo-v1"] + \
                 [s[0] for s in specs] + ["market-close-v1"]

    print(f"\n{'MARCADOR (solo temporadas de prueba)':44}{'log-loss':>10}"
          f"{'Brier':>9}{'acc':>8}{'n':>7}")
    print("  " + "-" * 76)
    results = {}
    for version in all_models:
        res, preds, actual = scoring.score_from_db(con, version, MARKET_1X2,
                                                   seasons=TEST)
        if res is None:
            continue
        results[version] = res
        scoring.save_metrics(con, version, MARKET_1X2, "test", res)
        scoring.save_calibration(con, version, MARKET_1X2, "test",
                                 scoring.calibration_bins(preds, actual))
        print(f"  {version:42}{res['log_loss']:>10.4f}{res['brier']:>9.4f}"
              f"{res['accuracy']*100:>7.1f}%{res['n_matches']:>7}")

    # Al ledger tambien: es la referencia contra la que el dashboard compara el
    # track record en vivo, y tiene que estar versionada para que se pueda leer
    # sin la base local.
    ledger.upsert_metrics([
        {"model_version": v, "market": MARKET_1X2, "eval_set": "test",
         "n_matches": r["n_matches"], "log_loss": f"{r['log_loss']:.6f}",
         "brier": f"{r['brier']:.6f}", "accuracy": f"{r['accuracy']:.6f}",
         "computed_at": ledger.now_iso()}
        for v, r in results.items()])

    # --- Cuanto del espacio disponible se cubrio -----------------------------
    floor = results["baseline-freq-v1"]["log_loss"]
    ceil = results["market-close-v1"]["log_loss"]
    span = floor - ceil
    print(f"\n  Piso (frecuencia base) {floor:.4f} · techo (mercado) {ceil:.4f}"
          f" · espacio {span:.4f}")
    print(f"\n  {'modelo':42}{'% del espacio cubierto':>24}")
    for version in all_models:
        if version in ("baseline-freq-v1", "market-close-v1"):
            continue
        pct = (floor - results[version]["log_loss"]) / span * 100
        print(f"  {version:42}{pct:>23.1f}%")

    # --- Veredicto, con prueba de significancia ------------------------------
    # El punto de esta seccion es no dejar que el script cante victoria por una
    # diferencia que cabe dentro del ruido. Un modelo "mejor" por 0.002 de
    # log-loss sobre 1730 partidos puede ser puro azar de que temporada toco.
    final = specs[-1][0]
    print(f"\n  {'comparacion pareada (temporadas de prueba)':46}"
          f"{'dif.':>9}{'IC 95%':>21}{'p':>8}")
    print("  " + "-" * 86)
    pairs = [(specs[1][0], specs[0][0], "aporte del decaimiento temporal"),
             (specs[2][0], specs[1][0], "aporte de rho (marcadores bajos)"),
             (specs[3][0], specs[2][0], "aporte de la regularizacion"),
             (final, "baseline-elo-v1", "modelo final  -  Elo"),
             (final, "market-close-v1", "modelo final  -  mercado")]
    verdicts = {}
    for a, b, label in pairs:
        out = scoring.paired_bootstrap(con, a, b, MARKET_1X2, seasons=TEST)
        if out is None:
            continue
        diff, lo, hi, pv, n = out
        concluyente = (lo > 0) == (hi > 0)
        verdicts[label] = (diff, concluyente)
        tag = "SIGNIFICATIVO" if concluyente else "no concluyente"
        print(f"  {label:46}{diff:>+9.4f} [{lo:>+7.4f},{hi:>+7.4f}]{pv:>8.3f}  {tag}")
    print("\n  Negativo = el primero es mejor. "
          "Si el intervalo contiene 0, la diferencia no se distingue del ruido.")

    diff, concluyente = verdicts["modelo final  -  Elo"]
    print(f"\n  VEREDICTO DE LA F2:")
    if diff < 0 and concluyente:
        print(f"    El modelo le gana a Elo por {abs(diff):.4f} y la diferencia es solida.")
    elif diff < 0:
        print(f"    El modelo queda por delante de Elo por {abs(diff):.4f}, pero el")
        print(f"    intervalo cruza cero: sobre esta muestra NO alcanza para declararlo")
        print(f"    mejor. Es un empate con ventaja, no una victoria.")
    else:
        print(f"    El modelo NO le gana a Elo. Elo sigue siendo la vara.")


if __name__ == "__main__":
    main()
