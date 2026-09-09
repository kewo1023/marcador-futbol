#!/usr/bin/env python3
"""F4 · Reentrena, desafia al campeon, y promueve solo si gana de verdad.

    ./.venv/bin/python scripts/06_retrain.py [--dry-run]

Corre semanalmente en GitHub Actions. Es la pieza que hace que el sistema
mejore solo Y no pueda empeorar.

COMO SE PARTEN LAS TEMPORADAS
-----------------------------
    entrenamiento    lo mas viejo      solo alimenta los ajustes
    afinado          3 temporadas      aqui se BUSCA el retador (xi, reg)
    gate             3 temporadas      aqui se DECIDE, y nada se busca

El bloque del gate no se toca durante la busqueda. Si se afinaran los
hiperparametros mirando el mismo periodo donde luego se decide, el retador
ganaria por haberse adaptado a esos partidos y no por ser mejor. Es la misma
trampa de la F2, movida un nivel arriba: no entra por las features, entra por
la decision de que configuracion proponer.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, promotion                    # noqa: E402
from marcador.backtest import ModelConfig                       # noqa: E402
from marcador.config import (LEAGUE, PRODUCTION_REG,            # noqa: E402
                             PRODUCTION_USE_RHO, PRODUCTION_XI, SEASONS)

# Cortes explicitos y no por indice: agregar una temporada nueva no debe mover
# en silencio un bloque y con el los numeros ya reportados.
GATE_SEASONS = ["2425", "2526", "2627"]
TUNE_SEASONS = ["2122", "2223", "2324"]

XI_GRID = [0.001, 0.0015, 0.002, 0.003, 0.004]
REG_GRID = [0.0, 0.001, 0.002, 0.005, 0.01, 0.02]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def search_challenger(matches):
    """Busca la mejor configuracion en el bloque de afinado."""
    print(f"Buscando retador en {len(TUNE_SEASONS)} temporadas de afinado "
          f"({TUNE_SEASONS[0]}-{TUNE_SEASONS[-1]}).")
    print("  Cada celda es el log-loss walk-forward de ese bloque.\n")
    print("  " + f"{'xi \\ reg':>10}" + "".join(f"{r:>9}" for r in REG_GRID))
    best, best_ll = None, float("inf")
    for xi in XI_GRID:
        cells = []
        for reg in REG_GRID:
            cfg = ModelConfig(xi=xi, reg=reg, use_rho=PRODUCTION_USE_RHO)
            _, losses = backtest.evaluate_config(matches, TUNE_SEASONS, cfg)
            ll = mean(losses)
            cells.append(ll)
            if ll < best_ll:
                best, best_ll = cfg, ll
        print(f"  {xi:>10}" + "".join(f"{c:>9.4f}" for c in cells))
    print(f"\n  Retador: {best.slug()}  (log-loss de afinado {best_ll:.4f})\n")
    return best


def align(a_ids, a_losses, b_ids, b_losses):
    """Deja las dos listas sobre EXACTAMENTE los mismos partidos y en el mismo
    orden. Sin esto el bootstrap pareado compararia peras con manzanas sin
    quejarse."""
    a = dict(zip(a_ids, a_losses))
    b = dict(zip(b_ids, b_losses))
    common = [i for i in a_ids if i in b]
    return common, [a[i] for i in common], [b[i] for i in common]


def main():
    dry = "--dry-run" in sys.argv
    con = db.init_db()
    matches = backtest.load_matches(con, LEAGUE)
    n_gate = sum(1 for m in matches if m["season"] in GATE_SEASONS)
    print(f"{len(matches)} partidos · bloque del gate: {n_gate} "
          f"({GATE_SEASONS[0]} a {GATE_SEASONS[-1]})\n")

    champ = promotion.read_champion()
    if champ is None:
        # Primera corrida: no hay campeon. Se instala la configuracion con la
        # que la F3 salio a produccion. Esto NO es una promocion —- no hubo
        # desafio— y se registra como inicializacion.
        cfg0 = ModelConfig(xi=PRODUCTION_XI, reg=PRODUCTION_REG,
                           use_rho=PRODUCTION_USE_RHO)
        print(f"No habia campeon. Se instala {cfg0.slug()} como punto de "
              f"partida (inicializacion, no promocion).\n")
        if not dry:
            promotion.write_champion(cfg0, "inicializacion: configuracion con "
                                           "la que salio a produccion la F3")
        champ_cfg = cfg0
    else:
        champ_cfg = champ["config"]
        print(f"Campeon actual: {champ_cfg.slug()}\n")

    challenger = search_challenger(matches)

    if challenger == champ_cfg:
        print(f"El retador es identico al campeon. No hay nada que decidir.")
        return 0

    print(f"Evaluando a los dos sobre el bloque del gate, con el mismo "
          f"procedimiento de reajuste:")
    c_ids, c_losses = backtest.evaluate_config(matches, GATE_SEASONS, champ_cfg)
    r_ids, r_losses = backtest.evaluate_config(matches, GATE_SEASONS, challenger)
    common, c_losses, r_losses = align(c_ids, c_losses, r_ids, r_losses)
    print(f"  campeon  {champ_cfg.slug():28} {mean(c_losses):.4f}")
    print(f"  retador  {challenger.slug():28} {mean(r_losses):.4f}")
    print(f"  sobre {len(common)} partidos que ninguno de los dos vio al afinarse\n")

    decision, reason, st = promotion.decide(c_losses, r_losses)

    print(f"  diferencia {st['diff']:+.4f}  IC 95% "
          f"[{st['ci_low']:+.4f}, {st['ci_high']:+.4f}]  p={st['p_value']:.3f}")
    print(f"\n  VEREDICTO: {decision}")
    print(f"  {reason}")

    row = {
        "decided_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gate_seasons": " ".join(GATE_SEASONS), "n_matches": st["n_matches"],
        "champion": champ_cfg.slug(), "challenger": challenger.slug(),
        "champion_logloss": f"{mean(c_losses):.6f}",
        "challenger_logloss": f"{mean(r_losses):.6f}",
        "diff": f"{st['diff']:.6f}", "ci_low": f"{st['ci_low']:.6f}",
        "ci_high": f"{st['ci_high']:.6f}", "p_value": f"{st['p_value']:.4f}",
        "decision": decision, "reason": reason,
    }
    if dry:
        print("\n--dry-run: no se escribio nada.")
        return 0

    promotion.record_challenge(row)
    if decision == promotion.PROMOTE:
        promotion.write_champion(challenger, reason, previous=champ_cfg.slug())
        print(f"\n  {challenger.slug()} pasa a produccion. Las predicciones "
              f"anteriores no se tocan.")
    else:
        print(f"\n  {champ_cfg.slug()} sigue en produccion. El desafio queda "
              f"registrado en ledger/challenges.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
