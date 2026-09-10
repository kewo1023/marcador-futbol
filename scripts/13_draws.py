#!/usr/bin/env python3
"""Atacar los empates: diagnostico, dos candidatos, y el gate.

    ./.venv/bin/python scripts/13_draws.py [--dry-run]

DE DONDE SALE
-------------
El diagnostico en cinco ligas (11_diagnose_multi.py) dejo UNA pista reforzada
al ampliar: la brecha contra el mercado en partidos que terminan en empate
pasa de +0.0103 (Premier) a +0.0207 (cinco ligas), concluyente. Las otras dos
"ventajas" de una liga se cayeron; esta se duplico.

LA MISMA DISCIPLINA QUE EL ATAQUE A LOS LOCALES
-----------------------------------------------
1. Confirmar que el problema existe en 2122-2324, temporadas que el
   diagnostico NO miro. Si la brecha solo esta donde se encontro la pista,
   es un artefacto.
2. Separar NIVEL de DISCRIMINACION. Nivel: ¿el modelo pone menos empate del
   que ocurre? Discriminacion: ¿separa peor que el mercado los partidos que
   empatan de los que no? Son enfermedades distintas con remedios distintos,
   y confundirlas fue el intento 2 de los locales.
3. Un candidato por causa, afinado en 2122-2324, juzgado en el gate contra
   el campeon COMPLETO (motor + capa de recalibracion), con bootstrap
   pareado. El campeon conserva el titulo salvo derrota concluyente.

LOS DOS CANDIDATOS
------------------
· DESPLAZAMIENTO DE EMPATE (`draw_shift`): un parametro que suma al logit de
  empate antes de la capa. Es una palanca de NIVEL. Ojo con lo que la
  bitacora registro el 09/09: la capa va sin interceptos porque con los tres
  el modelo movia masa hacia locales y empeoraba empates. Esto es distinto
  —un solo parametro, solo empate, elegido aparte— pero lo matiza, y por eso
  se dice aqui y no se esconde.
· FEATURES DE FORMA (`parity`, `pd_logit`): dos columnas mas en la capa,
  derivadas de las propias probabilidades del motor. Es una palanca de
  DISCRIMINACION: dejan que la capa estire o comprima la probabilidad de
  empate segun lo parejo del partido. Sin datos nuevos.
· Y la combinacion de las dos.
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, ledger, promotion, recalibration  # noqa: E402
from marcador.baseline import market_probs                          # noqa: E402
from marcador.config import LEAGUES, league_label                   # noqa: E402
from marcador.recalibration import FEATURES, OUTCOMES               # noqa: E402
from marcador.scoring import bootstrap_diff                         # noqa: E402

TUNE = ["2122", "2223", "2324"]
GATE = ["2425", "2526", "2627"]
ALL = TUNE + GATE
LAM_GRID = [10, 30, 100, 300, 1000]
SHIFT_GRID = [round(x, 2) for x in np.arange(-0.20, 0.31, 0.05)]
SHAPE = ["parity", "pd_logit"]
EPS = 1e-12
D = OUTCOMES.index("D")


def load_rows(con, league):
    return con.execute(
        """SELECT match_id, match_date, season, home_team, away_team, ftr,
                  fthg, ftag, hs, "as", hst, ast, hc, ac,
                  avgch, avgcd, avgca, psch, pscd, psca
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (league,)).fetchall()


def ll(probs, actual):
    return [-math.log(max(p[a], EPS)) for p, a in zip(probs, actual)]


def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.std() < 1e-12 or y.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main():
    dry = "--dry-run" in sys.argv
    con = db.init_db()
    champ = promotion.read_champion()
    cfg, spec = champ["config"], champ.get("recalibration") or {}
    champ_lam = spec.get("lam", 1000)
    print(f"Campeon: {champ['raw']['model_version']}  (capa: lam={champ_lam}, "
          f"{len(spec.get('features', FEATURES))} features)\n")

    # --- Cargar: motor walk-forward por liga, features de forma, mercado ----
    feats, by_id, P, order = {}, {}, {}, []
    for lg in LEAGUES:
        rows = load_rows(con, lg)
        feats.update(recalibration.rolling_features(rows, spec.get("window", 10)))
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

    def layer(train_s, test_s, features, lam, shift):
        """Probabilidades de la capa en test, entrenada en train. `shift` se
        suma al logit de empate del OFFSET, en train y en test: la capa se
        ajusta sabiendo que el empate ya fue desplazado."""
        tr_ids, tr_y = block(train_s)
        te_ids, _ = block(test_s)
        Xtr, otr, mu, sd = recalibration.design_matrix(tr_ids, P, feats,
                                                       features=features)
        Xte, ote, _, _ = recalibration.design_matrix(te_ids, P, feats, mu, sd,
                                                     features=features)
        otr, ote = otr.copy(), ote.copy()
        otr[:, D] += _shift_vec(tr_ids, shift)
        ote[:, D] += _shift_vec(te_ids, shift)
        b = recalibration.fit(Xtr, otr, tr_y, lam)
        pr = recalibration.predict(b, Xte, ote)
        return te_ids, [dict(zip(OUTCOMES, r)) for r in pr]

    def _shift_vec(ids, shift):
        """`shift` global (float) o por liga ({codigo: float})."""
        if isinstance(shift, dict):
            return np.array([shift.get(i.split("_")[0], 0.0) for i in ids])
        return np.full(len(ids), float(shift))

    def loso(features, lam, shift, only_league=None):
        """Validacion dejando una temporada fuera, dentro del afinado."""
        out = []
        for held in TUNE:
            ids, probs = layer([s for s in TUNE if s != held], [held],
                               features, lam, shift)
            if only_league:
                keep = [k for k, i in enumerate(ids) if i.startswith(only_league + "_")]
                ids, probs = [ids[k] for k in keep], [probs[k] for k in keep]
            out += ll(probs, [by_id[i]["ftr"] for i in ids])
        return float(np.mean(out))

    # =====================================================================
    # 1. CONFIRMAR EL PROBLEMA, EN TEMPORADAS QUE EL DIAGNOSTICO NO VIO
    # =====================================================================
    print("1. ¿EXISTE LA BRECHA EN EMPATES EN 2122-2324?  (el diagnostico miro 2425-2627)\n")
    tune_ids = []
    champ_tune = {}
    for held in TUNE:
        ids, probs = layer([s for s in TUNE if s != held], [held],
                           FEATURES, champ_lam, 0.0)
        tune_ids += ids
        champ_tune.update(dict(zip(ids, probs)))
    mkt = {i: market_probs(by_id[i]) for i in tune_ids}
    both = [i for i in tune_ids if mkt[i]]
    draws = [i for i in both if by_id[i]["ftr"] == "D"]

    def gap(ids, key):
        m = np.mean([-math.log(max(champ_tune[i][key(i)], EPS)) for i in ids])
        k = np.mean([-math.log(max(mkt[i][key(i)], EPS)) for i in ids])
        return m, k, m - k

    m, k, g = gap(both, lambda i: by_id[i]["ftr"])
    print(f"  todos los partidos ({len(both)}):   modelo {m:.4f}  mercado {k:.4f}  brecha {g:+.4f}")
    m, k, g = gap(draws, lambda i: "D")
    d_losses = ([-math.log(max(champ_tune[i]["D"], EPS)) for i in draws],
                [-math.log(max(mkt[i]["D"], EPS)) for i in draws])
    _, lo, hi, p, _ = bootstrap_diff(*d_losses)
    print(f"  solo empates ({len(draws)}):          modelo {m:.4f}  mercado {k:.4f}  "
          f"brecha {g:+.4f}  IC [{lo:+.4f},{hi:+.4f}]  "
          f"{'CONFIRMADA' if lo > 0 else 'no concluyente'}")

    # =====================================================================
    # 2. NIVEL O DISCRIMINACION
    # =====================================================================
    print("\n2. ¿NIVEL O DISCRIMINACION?\n")
    print(f"  {'liga':16}{'n':>6}{'empates reales':>16}{'modelo p(D)':>13}"
          f"{'mercado p(D)':>14}{'corr modelo':>13}{'corr mercado':>14}")
    tot = {"n": 0, "real": 0, "m": 0.0, "k": 0.0}
    xs_m, xs_k, ys = [], [], []
    for lg in LEAGUES:
        ids = [i for i in both if i.startswith(lg + "_")]
        if not ids:
            continue
        y = [1.0 if by_id[i]["ftr"] == "D" else 0.0 for i in ids]
        pm = [champ_tune[i]["D"] for i in ids]
        pk = [mkt[i]["D"] for i in ids]
        xs_m += pm; xs_k += pk; ys += y
        tot["n"] += len(ids); tot["real"] += sum(y)
        tot["m"] += sum(pm); tot["k"] += sum(pk)
        print(f"  {league_label(lg):16}{len(ids):>6}{np.mean(y):>15.1%}"
              f"{np.mean(pm):>13.1%}{np.mean(pk):>14.1%}"
              f"{corr(pm, y):>13.4f}{corr(pk, y):>14.4f}")
    print(f"  {'TODAS':16}{tot['n']:>6}{tot['real']/tot['n']:>15.1%}"
          f"{tot['m']/tot['n']:>13.1%}{tot['k']/tot['n']:>14.1%}"
          f"{corr(xs_m, ys):>13.4f}{corr(xs_k, ys):>14.4f}")
    level_gap = tot["m"] / tot["n"] - tot["real"] / tot["n"]
    disc_gap = corr(xs_k, ys) - corr(xs_m, ys)
    print(f"\n  nivel: el modelo pone {level_gap:+.1%} de empate respecto a lo que ocurre"
          f" (el mercado, {tot['k']/tot['n'] - tot['real']/tot['n']:+.1%}).")
    print(f"  discriminacion: correlacion con el empate {corr(xs_m, ys):.4f} contra "
          f"{corr(xs_k, ys):.4f} del mercado (diferencia {disc_gap:+.4f}).")

    # =====================================================================
    # 3. CANDIDATOS, AFINADOS EN 2122-2324
    # =====================================================================
    print("\n3. CANDIDATOS  (validacion dejando una temporada fuera, dentro de 2122-2324)\n")
    base_ll = loso(FEATURES, champ_lam, 0.0)
    print(f"  campeon (capa actual):                       {base_ll:.4f}")

    best_shift = min(SHIFT_GRID, key=lambda s: loso(FEATURES, champ_lam, s))
    ll_shift = loso(FEATURES, champ_lam, best_shift)
    print(f"  A. desplazamiento de empate  shift={best_shift:+.2f}:      {ll_shift:.4f}")

    best_lam = min(LAM_GRID, key=lambda l: loso(FEATURES + SHAPE, l, 0.0))
    ll_shape = loso(FEATURES + SHAPE, best_lam, 0.0)
    print(f"  B. features de forma         lam={best_lam}:          {ll_shape:.4f}")

    best_both = min(((l, s) for l in LAM_GRID for s in SHIFT_GRID),
                    key=lambda ls: loso(FEATURES + SHAPE, ls[0], ls[1]))
    ll_both = loso(FEATURES + SHAPE, *best_both)
    print(f"  C. las dos                   lam={best_both[0]}, shift={best_both[1]:+.2f}: "
          f"{ll_both:.4f}")

    # D. Un desplazamiento POR LIGA. La tabla de nivel no es uniforme: una liga
    # subestima el empate en casi tres puntos y otra lo clava; un shift global
    # promedia cinco cosas distintas. Cada liga elige el suyo mirando solo sus
    # partidos del bloque de afinado. Son cinco parametros en vez de uno: mas
    # capacidad de sobreajustar, y por eso el gate es quien decide.
    shift_by_lg = {}
    for lg in LEAGUES:
        shift_by_lg[lg] = min(SHIFT_GRID, key=lambda sh: loso(
            FEATURES, champ_lam, {lg: sh}, only_league=lg))
    ll_bylg = loso(FEATURES, champ_lam, shift_by_lg)
    print(f"  D. desplazamiento por liga   "
          f"{' '.join(f'{lg}:{v:+.2f}' for lg, v in shift_by_lg.items())}: {ll_bylg:.4f}")
    ll_e = loso(FEATURES + SHAPE, best_lam, shift_by_lg)
    print(f"  E. por liga + forma          lam={best_lam}:          {ll_e:.4f}")

    candidates = {
        "A-shift": (FEATURES, champ_lam, best_shift),
        "B-shape": (FEATURES + SHAPE, best_lam, 0.0),
        "C-both": (FEATURES + SHAPE, best_both[0], best_both[1]),
        "D-bylg": (FEATURES, champ_lam, shift_by_lg),
        "E-bylg+shape": (FEATURES + SHAPE, best_lam, shift_by_lg),
    }

    # =====================================================================
    # 4. EL GATE: 2425-2627, capa reentrenada con todo lo anterior
    # =====================================================================
    print("\n4. EL GATE  (2425-2627, la capa se reentrena con todo lo anterior a cada temporada)\n")

    def gate_probs(features, lam, shift):
        ids_all, probs_all = [], []
        for season in GATE:
            ids, probs = layer([s for s in ALL if s < season], [season],
                               features, lam, shift)
            ids_all += ids; probs_all += probs
        return ids_all, probs_all

    g_ids, champ_g = gate_probs(FEATURES, champ_lam, 0.0)
    actual = [by_id[i]["ftr"] for i in g_ids]
    champ_l = ll(champ_g, actual)
    mkt_g = {i: market_probs(by_id[i]) for i in g_ids}
    d_idx = [k for k, i in enumerate(g_ids) if actual[k] == "D" and mkt_g[i]]
    mkt_d = [-math.log(max(mkt_g[g_ids[k]]["D"], EPS)) for k in d_idx]
    champ_d = [champ_l[k] for k in d_idx]
    print(f"  campeon: {np.mean(champ_l):.4f} sobre {len(g_ids)} partidos · "
          f"brecha en empates vs mercado {np.mean(champ_d) - np.mean(mkt_d):+.4f} "
          f"({len(d_idx)} empates)")

    results = {}
    for name, (features, lam, shift) in candidates.items():
        ids, probs = gate_probs(features, lam, shift)
        assert ids == g_ids
        cand_l = ll(probs, actual)
        decision, reason, st = promotion.decide(champ_l, cand_l)
        cand_d = [cand_l[k] for k in d_idx]
        gap_after = np.mean(cand_d) - np.mean(mkt_d)
        pd_mean = np.mean([p["D"] for p in probs])
        results[name] = (decision, reason, st, gap_after, pd_mean)
        print(f"\n  {name:13} {np.mean(cand_l):.4f}  "
              f"dif {st['diff']:+.4f}  IC [{st['ci_low']:+.4f},{st['ci_high']:+.4f}]  "
              f"p={st['p_value']:.3f}  -> {decision}")
        print(f"                brecha en empates {gap_after:+.4f} · p(D) media {pd_mean:.1%}"
              f" · {reason}")

    # =====================================================================
    # 5. VEREDICTO
    # =====================================================================
    winners = {n: r for n, r in results.items() if r[0] == promotion.PROMOTE}
    print("\n5. VEREDICTO\n")
    if not winners:
        print("  Ningun candidato derrota al campeon de forma concluyente.")
        print("  El campeon conserva el titulo. Los numeros quedan en el ledger.")
    else:
        best = min(winners, key=lambda n: winners[n][2]["diff"])
        print(f"  {best} derrota al campeon: {winners[best][1]}.")
        if len(winners) > 1:
            print(f"  (tambien ganan: {', '.join(n for n in winners if n != best)};"
                  f" se toma el de mayor ganancia)")

    rows = [{"decided_at": ledger.now_iso(), "gate_seasons": " ".join(GATE),
             "champion": champ["raw"]["model_version"],
             "challenger": f"{champ['raw']['model_version']}+draws-{n}",
             "diff": f"{r[2]['diff']:.6f}", "ci_low": f"{r[2]['ci_low']:.6f}",
             "ci_high": f"{r[2]['ci_high']:.6f}", "p_value": f"{r[2]['p_value']:.4f}",
             "n_matches": r[2]["n_matches"], "decision": r[0],
             "champion_logloss": f"{np.mean(champ_l):.6f}",
             "challenger_logloss": f"{np.mean(champ_l) + r[2]['diff']:.6f}",
             "reason": r[1]} for n, r in results.items()]
    if dry:
        print("\n  --dry-run: no se escribio nada en el ledger.")
        return 0
    for r in rows:
        promotion.record_challenge(r)
    print(f"\n  {len(rows)} desafios registrados en ledger/challenges.csv.")
    if winners:
        best = min(winners, key=lambda n: winners[n][2]["diff"])
        features, lam, shift = candidates[best]
        new_spec = {**spec, "lam": lam, "features": list(features),
                    "draw_shift": shift}
        version = f"{cfg.slug()}+recal{lam}" + (
            f"+draws-{best.split('-')[1]}")
        promotion.write_champion(cfg, winners[best][1],
                                 previous=champ["raw"]["model_version"],
                                 recalibration=new_spec, version=version)
        print(f"  {version} pasa a produccion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
