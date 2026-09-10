#!/usr/bin/env python3
"""F1 · paso 1 — Baja los CSV históricos y los carga a SQLite.

    python3 scripts/01_ingest.py           # usa la cache de data/raw/
    python3 scripts/01_ingest.py --force   # vuelve a bajar todo

Idempotente: correrlo dos veces no duplica ni corrompe nada.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import db, ingest                    # noqa: E402
from marcador.config import (LEAGUES, SEASONS,      # noqa: E402
                             league_label, season_label)


def main():
    force = "--force" in sys.argv
    con = db.init_db()
    print(f"{len(LEAGUES)} ligas x {len(SEASONS)} temporadas "
          f"({season_label(SEASONS[0])} a {season_label(SEASONS[-1])})\n")

    for league, rows in ingest.ingest_leagues(con, LEAGUES, force=force).items():
        total = sum(r[1] for r in rows)
        fallos = [r for r in rows if r[1] == 0]
        print(f"  {league_label(league):16} {total:>5} partidos"
              + (f"   ({len(fallos)} temporadas sin datos)" if fallos else ""))

    print()
    q = """SELECT league, COUNT(*) n, MIN(match_date) a, MAX(match_date) b,
                  SUM(avgch IS NOT NULL OR psch IS NOT NULL) odds,
                  SUM(referee IS NOT NULL) ref
           FROM matches GROUP BY league ORDER BY league"""
    print(f"  {'liga':16}{'partidos':>10}{'con cuota':>11}{'con arbitro':>13}"
          f"   rango")
    for r in con.execute(q):
        print(f"  {league_label(r['league']):16}{r['n']:>10}{r['odds']:>11}"
              f"{r['ref']:>13}   {r['a']} a {r['b']}")
    total, = con.execute("SELECT COUNT(*) FROM matches").fetchone()
    print(f"\n  Total en la base: {total} partidos")


if __name__ == "__main__":
    main()
