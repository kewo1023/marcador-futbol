#!/usr/bin/env python3
"""F4 · Diagnostico automatico: donde pierde el modelo contra el mercado.

    ./.venv/bin/python scripts/07_diagnose.py

Alimenta la siguiente iteracion. NO decide nada: una pista encontrada aqui
tiene que pasar por el gate igual que cualquier otro cambio, y sobre datos que
no incluyan el bloque donde apareció la pista.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, diagnostics, promotion   # noqa: E402
from marcador.backtest import ModelConfig                   # noqa: E402
from marcador.config import LEAGUE, LEDGER_DIR              # noqa: E402

DIAG_FILE = LEDGER_DIR / "diagnostics.csv"
SEASONS_ANALYSED = ["2425", "2526", "2627"]


def main():
    con = db.init_db()
    champ = promotion.read_champion()
    cfg = champ["config"] if champ else ModelConfig()
    print(f"Diagnostico de {cfg.slug()} sobre {SEASONS_ANALYSED[0]}-"
          f"{SEASONS_ANALYSED[-1]}\n")

    matches = backtest.load_matches(con, LEAGUE)
    preds, _, _ = backtest.walk_forward(matches, SEASONS_ANALYSED, cfg)
    model_probs = {mid: {"probs": p} for mid, p, _ in preds}

    ctx = diagnostics.load_context(con, LEAGUE)
    rows, n = diagnostics.analyse(ctx, model_probs, SEASONS_ANALYSED)
    if not rows:
        print("Sin partidos suficientes para diagnosticar.")
        return 0

    total_gap = sum(r["peso"] for r in rows if r["segmento"] == "por resultado")
    print(f"Sobre {n} partidos con cuota de cierre disponible.")
    print(f"Brecha total contra el mercado: {total_gap:+.4f} de log-loss.\n")

    current = None
    for r in sorted(rows, key=lambda x: (x["segmento"], -x["peso"])):
        if r["segmento"] != current:
            current = r["segmento"]
            print(f"\n  {current.upper()}")
            print(f"  {'grupo':30}{'n':>6}{'modelo':>9}{'mercado':>9}"
                  f"{'brecha':>9}{'aporta':>9}")
        print(f"  {r['grupo']:30}{r['n']:>6}{r['modelo']:>9.4f}"
              f"{r['mercado']:>9.4f}{r['brecha']:>+9.4f}{r['peso']:>+9.4f}")

    print("\n  'brecha' = cuanto peor que el mercado en ESE grupo.")
    print("  'aporta' = cuanto de la brecha total viene de ese grupo "
          "(brecha x tamano).")
    print("  Un grupo con brecha grande pero pocos partidos importa poco;")
    print("  el que hay que atacar es el que mas aporta.\n")

    worst = max((r for r in rows if r["segmento"] == "por resultado"),
                key=lambda x: x["peso"])
    print(f"  Donde mas se pierde: {worst['grupo']} "
          f"({worst['n']} partidos, aporta {worst['peso']:+.4f})")

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with DIAG_FILE.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["modelo_version", "temporadas",
                                            "segmento", "grupo", "n", "modelo",
                                            "mercado", "brecha", "peso"])
        wr.writeheader()
        for r in rows:
            wr.writerow({"modelo_version": cfg.slug(),
                         "temporadas": " ".join(SEASONS_ANALYSED),
                         "segmento": r["segmento"], "grupo": r["grupo"],
                         "n": r["n"], "modelo": f"{r['modelo']:.6f}",
                         "mercado": f"{r['mercado']:.6f}",
                         "brecha": f"{r['brecha']:.6f}",
                         "peso": f"{r['peso']:.6f}"})
    print(f"  Guardado en {DIAG_FILE.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
