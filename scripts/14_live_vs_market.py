#!/usr/bin/env python3
"""Track record en vivo contra el mercado, con bootstrap pareado (regla 6).

    ./.venv/bin/python scripts/14_live_vs_market.py

Solo LEE el ledger (predictions, results, market_pre) y no toca la base ni
escribe nada, asi que se puede correr en local sin respaldo ni ledger de
prueba: no choca con la regla 8.

Para cada modelo en vivo y cada referencia de mercado (cierre y pre-partido)
dice la diferencia de log-loss sobre los MISMOS partidos, su intervalo del 95 %
y si es concluyente. Negativo = el modelo le gana al mercado.
"""
import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from marcador import scoring  # noqa: E402

# 05_score.py empieza con un numero y no se puede importar por nombre.
_spec = importlib.util.spec_from_file_location("score05", RAIZ / "scripts" / "05_score.py")
score05 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score05)

REFERENCIAS = (
    (score05.MARKET_REFERENCE, "cierre"),
    (score05.MARKET_PRE_REFERENCE, "pre-partido"),
)


def comparaciones():
    """Filas (modelo, mercado, referencia, diff, lo, hi, p, n) para todo lo comparable."""
    _, by_key = score05.score_live()
    filas = []
    for (mv, market, eval_set), partidos in sorted(by_key.items()):
        if eval_set != "live" or mv in (score05.MARKET_REFERENCE, score05.MARKET_PRE_REFERENCE,
                                        score05.BASE_MODEL_VERSION):
            continue
        for ref, etiqueta in REFERENCIAS:
            ref_partidos = by_key.get((ref, market, "live"))
            if not ref_partidos:
                continue
            res = scoring.live_paired(partidos, ref_partidos)
            if res:
                filas.append((mv, market, etiqueta, *res))
    return filas


def veredicto(lo, hi):
    if hi < 0:
        return "le gana al mercado"
    if lo > 0:
        return "pierde contra el mercado"
    return "no concluyente"


def main():
    filas = comparaciones()
    if not filas:
        print("Todavia no hay 30 partidos en comun entre un modelo y el mercado.")
        return 0
    print(f"{'modelo':38}{'mercado':>12}{'vs':>13}{'diff':>9}{'IC 95 %':>20}{'n':>5}  veredicto")
    print("-" * 112)
    for mv, market, ref, d, lo, hi, p, n in filas:
        print(f"{mv:38}{market:>12}{ref:>13}{d:>+9.4f}   [{lo:+.4f}, {hi:+.4f}]{n:>5}  {veredicto(lo, hi)}")
    print("\nNegativo = el modelo es mejor. Si el intervalo contiene 0, la diferencia no esta demostrada.")
    print("El ancho del intervalo dice cuanta diferencia se podria detectar con estos partidos (potencia).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
