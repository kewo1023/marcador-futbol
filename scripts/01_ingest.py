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
from marcador.config import LEAGUE, SEASONS, season_label  # noqa: E402


def main():
    force = "--force" in sys.argv
    con = db.init_db()
    print(f"Liga: {LEAGUE} · {len(SEASONS)} temporadas "
          f"({season_label(SEASONS[0])} a {season_label(SEASONS[-1])})\n")

    for season, n, size in ingest.ingest_all(con, force=force):
        print(f"  {season_label(season)}  {n:>4} partidos  ({size/1024:.0f} KB)")

    total, = con.execute("SELECT COUNT(*) FROM matches").fetchone()
    # Cuenta la cobertura EFECTIVA: el promedio de las casas, o Pinnacle donde
    # aquel no exista. Contar solo Pinnacle daba un 95% enganoso desde que la
    # fuente dejo de publicarla en enero de 2026.
    with_odds, = con.execute(
        "SELECT COUNT(*) FROM matches "
        "WHERE avgch IS NOT NULL OR psch IS NOT NULL").fetchone()
    with_ref, = con.execute(
        "SELECT COUNT(*) FROM matches WHERE referee IS NOT NULL").fetchone()
    with_corners, = con.execute(
        "SELECT COUNT(*) FROM matches WHERE hc IS NOT NULL").fetchone()
    lo, hi = con.execute(
        "SELECT MIN(match_date), MAX(match_date) FROM matches").fetchone()

    print(f"\n  Total en la base: {total} partidos  ({lo} a {hi})")
    print(f"  Con cuota de cierre: {with_odds} ({with_odds/total*100:.0f}%)")
    print(f"  Con corners:         {with_corners} ({with_corners/total*100:.0f}%)")
    print(f"  Con árbitro:         {with_ref} ({with_ref/total*100:.0f}%)")


if __name__ == "__main__":
    main()
