#!/usr/bin/env python3
"""Features de contexto, primer bloque: dias de descanso. Candidatos y gate.

    ./.venv/bin/python scripts/15_rest.py            # solo mide (no escribe nada)
    ./.venv/bin/python scripts/15_rest.py --record   # ademas deja los desafios en el ledger

DE DONDE SALE
-------------
El ataque a los empates (13_draws.py) cerro con cinco rechazos y una
conclusion: lo que le falta al modelo no es calibracion, es INFORMACION NUEVA.
Todo lo que la capa veia hasta hoy salia de los propios goles, tiros y
corners. Los dias de descanso son el primer dato que el modelo no tenia: cuanto
tiempo paso desde el partido anterior de cada equipo.

REGLA 4
-------
El descanso de un partido se calcula con la fecha del partido ANTERIOR de cada
equipo, que por construccion es anterior al kickoff. Se recorre la historia en
orden y el dato de un partido se fija antes de registrar ese partido.

LIMITE CONOCIDO
---------------
La base solo tiene partidos de liga. Un equipo que jugo copa o Europa a mitad
de semana aparece "descansado" cuando no lo esta. Por eso esto es un PROXY del
descanso real, y si el gate lo rechaza por falta de potencia, el siguiente
paso no es afinarlo sino conseguir el calendario completo.

LOS CANDIDATOS
--------------
· A-dif: la capa del campeon + `rest_dif` (descanso local menos visitante).
· B-dos: la capa del campeon + `rest_h` y `rest_a` por separado.
Descanso en dias, recortado a [2, 14]: menos de 2 es un dato raro, y mas de
14 (inicio de temporada, parones) ya no dice nada de cansancio.
"""
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, ledger, promotion, recalibration  # noqa: E402
from marcador.config import LEAGUES                                 # noqa: E402
from marcador.recalibration import FEATURES, OUTCOMES               # noqa: E402

TUNE = ["2122", "2223", "2324"]
GATE = ["2425", "2526", "2627"]
ALL = TUNE + GATE
LAM_GRID = [10, 30, 100, 300, 1000]
REST_MIN, REST_MAX = 2, 14
EPS = 1e-12


def load_rows(con, league):
    return con.execute(
        """SELECT match_id, match_date, season, home_team, away_team, ftr,
                  fthg, ftag, hs, "as", hst, ast, hc, ac
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (league,)).fetchall()


def rest_features(rows):
    """{match_id: {rest_h, rest_a, rest_dif}} con solo partidos anteriores.

    `rows` tiene que venir en orden de fecha. El ultimo partido de cada equipo
    se actualiza DESPUES de calcular el del partido actual: si dos partidos
    del mismo equipo cayeran el mismo dia, el segundo no ve al primero como
    anterior (se recorta a REST_MIN de todas formas).
    """
    last, out = {}, {}

    def days(team, d):
        prev = last.get(team)
        if prev is None:
            return REST_MAX
        return min(REST_MAX, max(REST_MIN, (d - prev).days))

    for r in rows:
        d = date.fromisoformat(str(r["match_date"])[:10])
        h, a = r["home_team"], r["away_team"]
        rh, ra = days(h, d), days(a, d)
        out[r["match_id"]] = {"rest_h": float(rh), "rest_a": float(ra),
                              "rest_dif": float(rh - ra)}
        last[h] = last[a] = d
    return out


def ll(probs, actual):
    return [-math.log(max(p[a], EPS)) for p, a in zip(probs, actual)]


def main():
    record = "--record" in sys.argv
    con = db.init_db()
    champ = promotion.read_champion()
    cfg, spec = champ["config"], champ.get("recalibration") or {}
    champ_lam = spec.get("lam", 1000)
    champ_feats = list(spec.get("features", FEATURES))
    print(f"Campeon: {champ['raw']['model_version']}  (capa: lam={champ_lam}, "
          f"{len(champ_feats)} features)\n")

    # --- Motor walk-forward por liga, features de forma y de descanso ---
    feats, by_id, P, order = {}, {}, {}, []
    for lg in LEAGUES:
        rows = load_rows(con, lg)
        feats.update(recalibration.rolling_features(rows, spec.get("window", 10)))
        for i, f in rest_features(rows).items():
            feats.setdefault(i, {}).update(f)
        by_id.update({r["match_id"]: r for r in rows})
        ms = backtest.load_matches(con, lg)
        preds, _, _ = backtest.walk_forward(ms, ALL, cfg)
        P.update({i: p for i, p, _ in preds})
        order += [m for m in ms if m["season"] in ALL and m["id"] in P]
    order.sort(key=lambda m: (m["season"], m["date"]))
    for i, f in recalibration.shape_features(P).items():
        feats.setdefault(i, {}).update(f)
    print(f"{len(order)} partidos, {len(LEAGUES)} ligas, {ALL[0]}-{ALL[-1]}\n")

    y_idx = {o: k for k, o in enumerate(OUTCOMES)}

    def block(seasons):
        ids = [m["id"] for m in order if m["season"] in seasons]
        return ids, np.array([y_idx[by_id[i]["ftr"]] for i in ids])

    def layer(train_s, test_s, features, lam):
        tr_ids, tr_y = block(train_s)
        te_ids, _ = block(test_s)
        Xtr, otr, mu, sd = recalibration.design_matrix(tr_ids, P, feats, features=features)
        Xte, ote, _, _ = recalibration.design_matrix(te_ids, P, feats, mu, sd, features=features)
        b = recalibration.fit(Xtr, otr, tr_y, lam)
        return te_ids, [dict(zip(OUTCOMES, r)) for r in recalibration.predict(b, Xte, ote)]

    def loso(features, lam):
        out = []
        for held in TUNE:
            ids, probs = layer([s for s in TUNE if s != held], [held], features, lam)
            out += ll(probs, [by_id[i]["ftr"] for i in ids])
        return float(np.mean(out))

    # =====================================================================
    # 1. ¿EL DESCANSO DICE ALGO QUE EL MOTOR NO SABE?  (solo 2122-2324)
    # =====================================================================
    print("1. ¿HAY SEÑAL?  (2122-2324: resultado del local segun la ventaja de descanso)\n")
    tune_ids, _ = block(TUNE)
    groups = {"local con 2+ dias menos": lambda x: x <= -2, "parejo (±1 dia)": lambda x: -1 <= x <= 1,
              "local con 2+ dias mas": lambda x: x >= 2}
    print(f"  {'grupo':28}{'n':>6}{'gana local':>12}{'modelo p(H)':>13}{'residuo':>10}")
    for name, cond in groups.items():
        ids = [i for i in tune_ids if cond(feats[i]["rest_dif"])]
        if not ids:
            continue
        real = np.mean([by_id[i]["ftr"] == "H" for i in ids])
        pm = np.mean([P[i]["H"] for i in ids])
        print(f"  {name:28}{len(ids):>6}{real:>11.1%}{pm:>13.1%}{real - pm:>+10.1%}")
    print("  (residuo = lo que el motor NO anticipa; si es ~0 en los tres grupos, no hay señal que capturar)")

    # =====================================================================
    # 2. CANDIDATOS, AFINADOS EN 2122-2324
    # =====================================================================
    print("\n2. CANDIDATOS  (validacion dejando una temporada fuera, dentro de 2122-2324)\n")
    print(f"  campeon (capa actual):                 {loso(champ_feats, champ_lam):.4f}")
    options = {"A-dif": champ_feats + ["rest_dif"], "B-dos": champ_feats + ["rest_h", "rest_a"]}
    candidates = {}
    for name, features in options.items():
        lam = min(LAM_GRID, key=lambda l: loso(features, l))
        candidates[name] = (features, lam)
        print(f"  {name:6} lam={lam:<5}                       {loso(features, lam):.4f}")

    # =====================================================================
    # 3. EL GATE: 2425-2627, capa reentrenada con todo lo anterior
    # =====================================================================
    print("\n3. EL GATE  (2425-2627, la capa se reentrena con todo lo anterior a cada temporada)\n")

    def gate_probs(features, lam):
        ids_all, probs_all = [], []
        for season in GATE:
            ids, probs = layer([s for s in ALL if s < season], [season], features, lam)
            ids_all += ids; probs_all += probs
        return ids_all, probs_all

    g_ids, champ_g = gate_probs(champ_feats, champ_lam)
    actual = [by_id[i]["ftr"] for i in g_ids]
    champ_l = ll(champ_g, actual)
    print(f"  campeon: {np.mean(champ_l):.4f} sobre {len(g_ids)} partidos")
    results = {}
    for name, (features, lam) in candidates.items():
        ids, probs = gate_probs(features, lam)
        assert ids == g_ids
        cand_l = ll(probs, actual)
        decision, reason, st = promotion.decide(champ_l, cand_l)
        results[name] = (decision, reason, st)
        half = (st["ci_high"] - st["ci_low"]) / 2
        print(f"\n  {name:6} {np.mean(cand_l):.4f}  dif {st['diff']:+.4f}  "
              f"IC [{st['ci_low']:+.4f},{st['ci_high']:+.4f}]  p={st['p_value']:.3f}  -> {decision}")
        print(f"         {reason}")
        print(f"         potencia: con {st['n_matches']} partidos el gate solo distingue "
              f"diferencias de ~{half:.4f} o mas")

    # =====================================================================
    # 4. VEREDICTO
    # =====================================================================
    winners = {n: r for n, r in results.items() if r[0] == promotion.PROMOTE}
    print("\n4. VEREDICTO\n")
    if not winners:
        print("  Ningun candidato derrota al campeon de forma concluyente. El campeon sigue.")
    else:
        best = min(winners, key=lambda n: winners[n][2]["diff"])
        print(f"  {best} derrota al campeon: {winners[best][1]}.")
        print("  NO pasa a produccion desde aqui: 04_predict todavia no calcula el descanso")
        print("  de los partidos por jugar. Eso es el siguiente bloque.")

    rows = [{"decided_at": ledger.now_iso(), "gate_seasons": " ".join(GATE),
             "champion": champ["raw"]["model_version"],
             "challenger": f"{champ['raw']['model_version']}+rest-{n}",
             "diff": f"{r[2]['diff']:.6f}", "ci_low": f"{r[2]['ci_low']:.6f}",
             "ci_high": f"{r[2]['ci_high']:.6f}", "p_value": f"{r[2]['p_value']:.4f}",
             "n_matches": r[2]["n_matches"], "decision": r[0],
             "champion_logloss": f"{np.mean(champ_l):.6f}",
             "challenger_logloss": f"{np.mean(champ_l) + r[2]['diff']:.6f}",
             "reason": r[1]} for n, r in results.items()]
    if not record:
        print("\n  Sin --record: no se escribio nada en el ledger.")
        return 0
    for r in rows:
        promotion.record_challenge(r)
    print(f"\n  {len(rows)} desafios registrados en ledger/challenges.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
