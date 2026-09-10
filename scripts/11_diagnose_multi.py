#!/usr/bin/env python3
"""Diagnostico sobre las CINCO ligas, con la regla 6 aplicada por segmento.

    ./.venv/bin/python scripts/11_diagnose_multi.py

POR QUE ESTE SCRIPT EXISTE APARTE DE 07
---------------------------------------
`07_diagnose.py` sigue mirando una sola liga, y se queda asi a proposito: sus
numeros estan citados en el README y en los aprendizajes, y moverlos romperia
la trazabilidad de lo ya publicado. Este script no lo reemplaza ni lo modifica;
escribe en otro archivo del ledger y se lee al lado del otro.

LO QUE CAMBIA AL PASAR DE UNA LIGA A CINCO
------------------------------------------
No es "el mismo diagnostico con mas datos". Es un diagnostico que puede
responder una pregunta que el de una liga no podia:

    07 ordena los segmentos por cuanto aportan a la brecha total.
    Este dice ademas si esa brecha se distingue del ruido.

Con 790 partidos, partir el bloque en segmentos dejaba grupos de 100 o 200
partidos: suficiente para calcular un promedio, no para creerselo. Con ~3650
partidos con cuota de cierre los grupos crecen lo bastante para meterles el
mismo bootstrap pareado que usa el gate de la F4.

Eso importa porque el diagnostico es un generador de hipotesis, y una hipotesis
falsa cuesta caro: las F5 y F7 salieron de mirar este tipo de tabla, y la
sesion de los empates gasto tres intentos. Saber de antemano cuales grupos
tienen brecha demostrable y cuales no es exactamente lo que evita ese gasto.

EL SEGMENTO NUEVO: POR LIGA
---------------------------
Con una liga no existia. Es la primera pregunta que cinco ligas habilitan: si
el modelo pierde parejo contra el mercado en todas, el problema es del modelo;
si pierde en una sola, el problema es de esa liga.

LO QUE ESTE SCRIPT NO HACE
--------------------------
No decide nada. Una pista de aqui pasa por el gate igual que cualquier otra, y
sobre temporadas que este diagnostico no haya mirado — si no, se estaria
confirmando la pista con los datos que la produjeron.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import backtest, db, diagnostics, promotion   # noqa: E402
from marcador.backtest import ModelConfig                   # noqa: E402
from marcador.config import LEAGUES, LEDGER_DIR, league_label  # noqa: E402

DIAG_FILE = LEDGER_DIR / "diagnostics_multi.csv"

# Las mismas que mira 07, para que las dos tablas se puedan leer una al lado
# de la otra sin tener que corregir por periodo.
SEASONS_ANALYSED = ["2425", "2526", "2627"]


def main():
    con = db.init_db()
    champ = promotion.read_champion()
    cfg = champ["config"] if champ else ModelConfig()
    leagues = list(LEAGUES)
    print(f"Diagnostico de {cfg.slug()} sobre {SEASONS_ANALYSED[0]}-"
          f"{SEASONS_ANALYSED[-1]}, {len(leagues)} ligas\n")

    # Un ajuste por liga: los equipos no se solapan, asi que un ajuste conjunto
    # exigiria efectos de liga. Lo que se junta son las perdidas por partido,
    # que si son comparables entre competiciones (decision del 2026-09-10).
    model_probs, ctx = {}, []
    print(f"  {'liga':18}{'partidos':>10}{'reajustes':>11}")
    for lg in leagues:
        matches = backtest.load_matches(con, lg)
        preds, n_fits, _ = backtest.walk_forward(matches, SEASONS_ANALYSED, cfg)
        model_probs.update({mid: {"probs": p} for mid, p, _ in preds})
        ctx += diagnostics.load_context(con, lg)
        print(f"  {league_label(lg):18}{len(preds):>10}{n_fits:>11}")

    rows, n = diagnostics.analyse_paired(
        ctx, model_probs, SEASONS_ANALYSED,
        extra_segments=[("por liga", lambda m: league_label(m["league"]))])
    if not rows:
        print("\nSin partidos suficientes para diagnosticar.")
        return 0

    total_gap = sum(r["peso"] for r in rows if r["segmento"] == "por resultado")
    print(f"\nSobre {n} partidos con cuota de cierre disponible.")
    print(f"Brecha total contra el mercado: {total_gap:+.4f} de log-loss.\n")

    current = None
    for r in sorted(rows, key=lambda x: (x["segmento"], -x["peso"])):
        if r["segmento"] != current:
            current = r["segmento"]
            print(f"\n  {current.upper()}")
            print(f"  {'grupo':30}{'n':>6}{'modelo':>9}{'mercado':>9}"
                  f"{'brecha':>9}{'aporta':>9}{'IC 95% de la brecha':>24}"
                  f"{'':>4}")
        marca = "  <- real" if r["concluyente"] else ""
        print(f"  {r['grupo']:30}{r['n']:>6}{r['modelo']:>9.4f}"
              f"{r['mercado']:>9.4f}{r['brecha']:>+9.4f}{r['peso']:>+9.4f}"
              f"   [{r['ci_low']:>+7.4f},{r['ci_high']:>+7.4f}]{marca}")

    print("\n  'brecha' = cuanto peor que el mercado en ESE grupo.")
    print("  'aporta' = cuanto de la brecha total viene de ese grupo "
          "(brecha x tamano).")
    print("  'real'   = el intervalo del bootstrap pareado no cruza cero. Sin")
    print("             esa marca, la brecha del grupo NO se distingue del")
    print("             ruido y no sirve como hipotesis (regla 6).\n")

    # --- Lo que solo se puede decir con la marca de concluyente -------------
    reales = [r for r in rows if r["concluyente"] and r["brecha"] > 0]
    ruido = [r for r in rows if not r["concluyente"]]
    print(f"  {len(reales)} de {len(rows)} grupos tienen brecha demostrable; "
          f"{len(ruido)} caben dentro del ruido.")

    # 'aporta' solo es comparable DENTRO de un segmento: cada segmento es una
    # particion distinta del mismo conjunto, asi que el maximo global no
    # significa nada — lo gana siempre el lado grande de un corte desbalanceado
    # ("sin tarjeta roja" son 5 de cada 6 partidos). Por eso 07 se limitaba a
    # "por resultado", y por eso aqui se reporta un lider por segmento.
    print(f"\n  DONDE MAS SE PIERDE, dentro de cada corte")
    print(f"  {'segmento':34}{'grupo que mas aporta':26}{'aporta':>9}"
          f"{'demostrable':>13}")
    for seg in sorted({r["segmento"] for r in rows}):
        peor = max((r for r in rows if r["segmento"] == seg),
                   key=lambda x: x["peso"])
        print(f"  {seg:34}{peor['grupo']:26}{peor['peso']:>+9.4f}"
              f"{('si' if peor['concluyente'] else 'NO — es ruido'):>13}")

    # --- Que pistas de una sola liga sobreviven al ampliar -------------------
    # El motivo entero del script. Una brecha medida sobre 790 partidos puede
    # ser una pista o puede ser el azar de que temporada tocó, y con esa muestra
    # no habia forma de saber cual de las dos. Aqui si.
    una_liga = LEDGER_DIR / "diagnostics.csv"
    if una_liga.exists():
        with una_liga.open(encoding="utf-8") as fh:
            antes = {(r["segmento"], r["grupo"]): float(r["brecha"])
                     for r in csv.DictReader(fh)}
        comunes = [r for r in rows if (r["segmento"], r["grupo"]) in antes]
        if comunes:
            print(f"\n  QUE PASA CON LAS PISTAS DE UNA SOLA LIGA")
            print(f"  {'corte · grupo':44}{'1 liga':>9}{'5 ligas':>9}{'':>3}"
                  f"{'veredicto':<32}")
            for r in sorted(comunes, key=lambda x: -abs(x["peso"])):
                b0, b1 = antes[(r["segmento"], r["grupo"])], r["brecha"]
                # El vuelco se reporta primero aunque no sea concluyente: que
                # una brecha A FAVOR del modelo desaparezca al ampliar dice
                # bastante mas que "no demostrable", y es el caso que habria
                # mandado a alguien a construir sobre una ventaja inexistente.
                if b0 <= 0 < b1 and not r["concluyente"]:
                    v = "SE DA VUELTA, y ya no se distingue"
                elif b0 <= 0 < b1:
                    v = "SE DA VUELTA: era a favor"
                elif not r["concluyente"]:
                    v = "sigue sin poder demostrarse"
                elif b1 > b0 * 1.5:
                    v = "confirmada, y mayor"
                else:
                    v = "confirmada"
                etiqueta = f"{r['segmento']} · {r['grupo']}"
                print(f"  {etiqueta[:43]:44}{b0:>+9.4f}{b1:>+9.4f}   {v:<32}")
            print("\n  Una brecha que se da vuelta al ampliar nunca fue una")
            print("  pista: era el azar de que temporada tocó en una liga.")

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    campos = ["modelo_version", "temporadas", "ligas", "segmento", "grupo", "n",
              "modelo", "mercado", "brecha", "peso", "ci_low", "ci_high",
              "p_value", "concluyente"]
    with DIAG_FILE.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=campos)
        wr.writeheader()
        for r in rows:
            wr.writerow({"modelo_version": cfg.slug(),
                         "temporadas": " ".join(SEASONS_ANALYSED),
                         "ligas": " ".join(leagues),
                         "segmento": r["segmento"], "grupo": r["grupo"],
                         "n": r["n"], "modelo": f"{r['modelo']:.6f}",
                         "mercado": f"{r['mercado']:.6f}",
                         "brecha": f"{r['brecha']:.6f}",
                         "peso": f"{r['peso']:.6f}",
                         "ci_low": f"{r['ci_low']:.6f}",
                         "ci_high": f"{r['ci_high']:.6f}",
                         "p_value": f"{r['p_value']:.4f}",
                         "concluyente": "si" if r["concluyente"] else "no"})
    print(f"\n  Guardado en {DIAG_FILE.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
