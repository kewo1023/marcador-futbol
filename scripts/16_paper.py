#!/usr/bin/env python3
"""Tablero de decision y paper trading, desde el ledger.

    ./.venv/bin/python scripts/16_paper.py

Solo LEE el ledger (predictions, results, market_pre, fixtures) y no escribe
nada, como 14_live_vs_market.py: se puede correr en local sin chocar con la
regla 8.

Dice tres cosas:
1. El semaforo de cada mercado con precio: ¿el modelo le gana al mercado, de
   forma demostrada? Sin verde, la recomendacion es no apostar.
2. Paper trading de dos reglas sobre los partidos ya jugados: las 10 mas
   probables de cada jornada, y valor (modelo > mercado pre). ROI a la cuota
   sin margen (techo), ROI con el margen tipico (lo realista) y CLV.
3. Las 10 mas probables de la proxima jornada, con su cuota minima: un solo
   lado por partido y mercado, y menos de 10 si ya no quedan mas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import betting, ledger, live_markets, promotion  # noqa: E402
from marcador.config import LIVE_MARKETS                       # noqa: E402

OUTCOME_LABEL = {"H": "local", "D": "empate", "A": "visitante",
                 "OVER": "más de", "UNDER": "menos de"}


def production_versions():
    """Las model_version en produccion hoy: el campeon del 1X2 y la de cada
    familia over/under (goles, tarjetas, tiros)."""
    champ = promotion.read_champion()
    if not champ:
        return set()
    return {champ["raw"]["model_version"]} | {
        live_markets.market_version(champ["config"], k) for k in LIVE_MARKETS}


def fmt_ci(t, pct=True):
    m, lo, hi = t
    if m is None:
        return "—"
    f = (lambda x: f"{x*100:+.1f}%") if pct else (lambda x: f"{x:+.4f}")
    if lo is None:
        return f"{f(m)} (sin IC: <{betting.MIN_MATCHES})"
    return f"{f(m)} [{f(lo)}, {f(hi)}]"


def main():
    versions = production_versions()
    pre = betting.pre_before_kickoff(ledger.read_market_pre(), ledger.read_fixtures())
    sels = betting.selections(ledger.read_predictions(), pre, versions)
    results = {r["match_id"]: r for r in ledger.read_results()}

    print("SEMAFORO (bootstrap pareado contra el mercado, regla 6)")
    for market in betting.PRICED_MARKETS:
        state, detail = betting.traffic_light(sels, results, pre, market)
        print(f"  {market:12} {state.upper():9} {betting.ADVICE[state]}")
        for ref, res in detail.items():
            if res:
                d, lo, hi, _, n = res
                print(f"      vs {ref:12} {d:+.4f} [{lo:+.4f}, {hi:+.4f}]  n={n}")
    print("  Tarjetas y tiros: GRIS. " + betting.ADVICE["gris"])

    print("\nPAPER TRADING (1 unidad por apuesta, partidos ya jugados)")
    for key, (label, s, _) in betting.paper_trading(sels, results).items():
        hit = f"{s['hit_rate']*100:.0f}%" if s["hit_rate"] is not None else "—"
        print(f"  {label}")
        print(f"      apuestas {s['n']:4}  acierto {hit}")
        print(f"      ROI sin margen (techo) {fmt_ci(s['roi_fair'])}")
        print(f"      ROI con margen {betting.TYPICAL_MARGIN:.1%}    {fmt_ci(s['roi_net'])}")
        print(f"      CLV ({s['n_clv']} con cierre)   {fmt_ci(s['clv'], pct=True)}")

    # Por jugar = kickoff por delante (o, sin hora, fecha de hoy en adelante).
    # "Sin resultado" no sirve: un partido aplazado o atrasado en la fuente
    # tambien esta sin resultado y no es la proxima jornada.
    now = ledger.now_iso()[:16]
    today = now[:10]
    kickoff = {r["match_id"]: r.get("kickoff_utc") or "" for r in ledger.read_fixtures()}
    pending = [s for s in sels if s["match_id"] not in results
               and (kickoff.get(s["match_id"]) > now if kickoff.get(s["match_id"])
                    else s["match_date"] >= today)]
    if pending:
        nxt = min(s["jornada"] for s in pending)
        top = betting.top_by_jornada([s for s in pending if s["jornada"] == nxt],
                                     priced_only=False)
        title = f"LAS {len(top)} MAS PROBABLES · jornada del {nxt}"
        if top and len(top) < 10:
            title += f" · quedan {len({s['match_id'] for s in top})} partidos por jugar"
        print(f"\n{title}")
        print(f"  {'partido':40}{'mercado':>20}{'modelo':>8}{'mercado':>9}{'cuota min':>10}")
        for s in top:
            sel = f"{s['market']} {OUTCOME_LABEL.get(s['outcome'], s['outcome'])}"
            mk = f"{s['p_pre']*100:.1f}%" if s["p_pre"] is not None else "—"
            print(f"  {s['home_team'] + ' vs ' + s['away_team']:40}{sel:>20}"
                  f"{s['p_model']*100:>7.1f}%{mk:>9}{s['min_odds']:>10.2f}")
        print("  Cuota minima = 1 / probabilidad del modelo. Ninguna fila es una "
              "recomendacion: eso lo decide el semaforo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
