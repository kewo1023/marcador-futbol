#!/usr/bin/env python3
"""Candidato: capa de recalibracion con forma reciente, contra el gate.

    ./.venv/bin/python scripts/10_recalibrate.py [--dry-run]

Ataca el frente que dejo abierto el diagnostico de la F4: el modelo pierde
contra el mercado sobre todo en victorias locales, y lo hace por discriminar
peor, no por tener mal el nivel.

La capa se afina en el bloque de afinado y se juzga en el del gate, con las
mismas reglas que cualquier otro candidato: el campeon conserva el titulo
salvo que lo derroten de forma concluyente.
"""
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, promotion, recalibration    # noqa: E402
from marcador.config import LEAGUES, league_label              # noqa: E402
from marcador.scoring import bootstrap_diff                     # noqa: E402

TUNE = ["2122", "2223", "2324"]
GATE = ["2425", "2526", "2627"]
ALL = TUNE + GATE
LAM_GRID = [1, 3, 10, 30, 100, 300, 1000]
EPS = 1e-12


def load_rows(con, league):
    return con.execute(
        """SELECT match_id, match_date, season, home_team, away_team, ftr,
                  fthg, ftag, hs, "as", hst, ast, hc, ac
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (league,)).fetchall()


def losses(probs, actual):
    return [-math.log(max(p[a], EPS)) for p, a in zip(probs, actual)]


def main():
    dry = "--dry-run" in sys.argv
    con = db.init_db()
    champ = promotion.read_champion()
    cfg = champ["config"]
    print(f"Campeon: {cfg.slug()}")

    # Las features de forma se calculan por liga (una racha es de un equipo
    # dentro de su competicion), y el modelo tambien se ajusta por liga. Lo que
    # se junta despues son las probabilidades y las perdidas, que si son
    # comparables entre ligas.
    feats, by_id, P, order, league_of = {}, {}, {}, [], {}
    for lg in LEAGUES:
        rows = load_rows(con, lg)
        feats.update(recalibration.rolling_features(rows))
        by_id.update({r["match_id"]: r for r in rows})
        ms = backtest.load_matches(con, lg)
        preds, _, _ = backtest.walk_forward(ms, ALL, cfg)
        P.update({i: p for i, p, _ in preds})
        sel = [m for m in ms if m["season"] in ALL and m["id"] in P]
        order += sel
        for m in sel:
            league_of[m["id"]] = lg
    order.sort(key=lambda m: (m["season"], m["date"]))
    print(f"{len(order)} partidos con prediccion del modelo, "
          f"{len(LEAGUES)} ligas ({ALL[0]}-{ALL[-1]})\n")

    y_idx = {o: i for i, o in enumerate(recalibration.OUTCOMES)}

    def block(seasons):
        ids = [m["id"] for m in order if m["season"] in seasons]
        y = np.array([y_idx[by_id[i]["ftr"]] for i in ids])
        return ids, y

    # --- Elegir lambda: validacion dejando una temporada fuera, DENTRO del
    #     bloque de afinado. El bloque del gate no se toca aqui.
    print("Eligiendo la fuerza de regularizacion en el bloque de afinado.")
    print("  lambda alto = la capa casi no toca al modelo.\n")
    print(f"  {'lambda':>8}{'log-loss (val. por temporada)':>32}")
    best_lam, best_ll = None, float("inf")
    for lam in LAM_GRID:
        fold_ll = []
        for held in TUNE:
            tr_s = [s for s in TUNE if s != held]
            tr_ids, tr_y = block(tr_s)
            te_ids, te_y = block([held])
            Xtr, otr, mu, sd = recalibration.design_matrix(tr_ids, P, feats)
            b = recalibration.fit(Xtr, otr, tr_y, lam)
            Xte, ote, _, _ = recalibration.design_matrix(te_ids, P, feats, mu, sd)
            pr = recalibration.predict(b, Xte, ote)
            fold_ll.append(np.mean(-np.log(np.clip(
                pr[np.arange(len(te_y)), te_y], EPS, 1))))
        ll = float(np.mean(fold_ll))
        mark = ""
        if ll < best_ll:
            best_lam, best_ll, mark = lam, ll, "  <- mejor"
        print(f"  {lam:>8}{ll:>32.4f}{mark}")
    base_ids, base_y = block(TUNE)
    base_ll = np.mean([-math.log(max(P[i][by_id[i]["ftr"]], EPS)) for i in base_ids])
    print(f"\n  el modelo sin capa, en el mismo bloque: {base_ll:.4f}")
    print(f"  lambda elegido: {best_lam}\n")

    # --- El gate: la capa se reajusta con TODO lo anterior a cada temporada.
    print("Evaluando en el bloque del gate, temporada por temporada.")
    print("  La capa se reentrena con todo lo anterior a cada una.\n")
    cand_probs, champ_probs, actual, cand_ids = [], [], [], []
    for season in GATE:
        train_s = [s for s in ALL if s < season]
        tr_ids, tr_y = block(train_s)
        te_ids, te_y = block([season])
        if not te_ids:
            continue
        Xtr, otr, mu, sd = recalibration.design_matrix(tr_ids, P, feats)
        b = recalibration.fit(Xtr, otr, tr_y, best_lam)
        Xte, ote, _, _ = recalibration.design_matrix(te_ids, P, feats, mu, sd)
        pr = recalibration.predict(b, Xte, ote)
        for row, i in zip(pr, te_ids):
            cand_probs.append(dict(zip(recalibration.OUTCOMES, row)))
            champ_probs.append(P[i])
            actual.append(by_id[i]["ftr"])
            cand_ids.append(i)
        ll_c = np.mean([-math.log(max(d[a], EPS)) for d, a in
                        zip(cand_probs[-len(te_ids):], actual[-len(te_ids):])])
        ll_m = np.mean([-math.log(max(P[i][by_id[i]["ftr"]], EPS)) for i in te_ids])
        print(f"  {season}  n={len(te_ids):>5}  campeon {ll_m:.4f}  "
              f"candidato {ll_c:.4f}  {ll_m - ll_c:+.4f}")

    lc = losses(cand_probs, actual)
    lm = losses(champ_probs, actual)
    print(f"\n  TOTAL   n={len(actual):>5}  campeon {np.mean(lm):.4f}  "
          f"candidato {np.mean(lc):.4f}")

    # Desglose por liga: una mejora que solo aparece en una liga es sospechosa.
    print(f"\n  {'liga':16}{'n':>7}{'campeon':>10}{'candidato':>11}{'dif.':>9}")
    ids_order = [i for i in cand_ids]
    for lg in LEAGUES:
        idx = [k for k, i in enumerate(ids_order) if league_of[i] == lg]
        if not idx:
            continue
        a = np.mean([lm[k] for k in idx]); b = np.mean([lc[k] for k in idx])
        print(f"  {league_label(lg):16}{len(idx):>7}{a:>10.4f}{b:>11.4f}"
              f"{b - a:>+9.4f}")

    decision, reason, st = promotion.decide(lm, lc)
    print(f"\n  diferencia {st['diff']:+.4f}  IC 95% "
          f"[{st['ci_low']:+.4f}, {st['ci_high']:+.4f}]  p={st['p_value']:.3f}")
    print(f"\n  VEREDICTO: {decision}")
    print(f"  {reason}")

    # ¿Y el frente que se queria atacar?
    h = [i for i, a in enumerate(actual) if a == "H"]
    print(f"\n  Solo victorias locales (n={len(h)}): campeon "
          f"{np.mean([lm[i] for i in h]):.4f}  candidato "
          f"{np.mean([lc[i] for i in h]):.4f}")
    ph_c = np.array([cand_probs[i]["H"] for i in range(len(actual))])
    ph_m = np.array([champ_probs[i]["H"] for i in range(len(actual))])
    won = np.array([a == "H" for a in actual])
    print(f"  correlacion con victoria local: campeon "
          f"{np.corrcoef(ph_m, won)[0, 1]:.4f}  candidato "
          f"{np.corrcoef(ph_c, won)[0, 1]:.4f}")

    # --- ¿Tiene el gate potencia para juzgar algo de este tamano? ----------
    sd = float(np.std(np.array(lc) - np.array(lm), ddof=1))
    mde = 1.96 * sd / math.sqrt(len(lc))
    need = int((1.96 * sd / abs(st["diff"])) ** 2) if st["diff"] else 0
    print(f"\n  POTENCIA DEL GATE")
    print(f"    con {len(lc)} partidos solo puede declarar concluyentes")
    print(f"    diferencias de {mde:.4f} o mayores.")
    if decision == promotion.PROMOTE:
        print(f"    la diferencia medida ({st['diff']:+.4f}) esta por encima de ese")
        print(f"    umbral, y por eso se pudo declarar. Con una sola liga (790")
        print(f"    partidos) el umbral era 0.0060 y esta misma capa fue rechazada.")
    else:
        print(f"    para que {st['diff']:+.4f} lo fuera harian falta ~{need} partidos.")
        print(f"    El rechazo NO dice que la capa no sirva: dice que con estos")
        print(f"    datos no se puede demostrar que sirva.")

    row = {
        "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gate_seasons": " ".join(GATE), "n_matches": st["n_matches"],
        "champion": cfg.slug(), "challenger": f"{cfg.slug()}+recal-lam{best_lam}",
        "champion_logloss": f"{np.mean(lm):.6f}",
        "challenger_logloss": f"{np.mean(lc):.6f}",
        "diff": f"{st['diff']:.6f}", "ci_low": f"{st['ci_low']:.6f}",
        "ci_high": f"{st['ci_high']:.6f}", "p_value": f"{st['p_value']:.4f}",
        "decision": decision, "reason": reason,
    }
    if dry:
        print("\n  --dry-run: no se escribio nada.")
        return 0
    promotion.record_challenge(row)
    print(f"\n  Desafio registrado en ledger/challenges.csv")
    if decision == promotion.PROMOTE:
        version = f"{cfg.slug()}+recal{best_lam}"
        promotion.write_champion(
            cfg, reason, previous=champ["raw"]["model_version"],
            recalibration={"lam": best_lam, "window": 10,
                           "features": recalibration.FEATURES,
                           "train_seasons": ALL},
            version=version)
        print(f"  {version} pasa a produccion.")
        print(f"  Las predicciones ya emitidas no se tocan: llevan el nombre")
        print(f"  del modelo que las genero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
