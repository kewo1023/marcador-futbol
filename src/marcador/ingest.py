"""Ingesta: baja los CSV de la fuente y los carga a SQLite.

Es idempotente. Correrlo dos veces no duplica partidos: cada partido tiene un
match_id determinístico y se usa INSERT ... ON CONFLICT DO UPDATE.
"""
import csv
import datetime as dt
import io
import urllib.request
from pathlib import Path

from .config import LEAGUE, RAW_DIR, SEASONS, USER_AGENT, season_url

# Columnas de la fuente -> columnas de la tabla. Lo que no esté aquí se ignora.
FIELD_MAP = {
    "FTHG": "fthg", "FTAG": "ftag", "FTR": "ftr",
    "HC": "hc", "AC": "ac",
    "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
    "HS": "hs", "AS": "as", "HST": "hst", "AST": "ast",
    "Referee": "referee",
    "PSCH": "psch", "PSCD": "pscd", "PSCA": "psca",
}
INT_COLS = {"fthg", "ftag", "hc", "ac", "hy", "ay", "hr", "ar",
            "hs", "as", "hst", "ast"}
FLOAT_COLS = {"psch", "pscd", "psca"}


def parse_date(raw: str) -> str | None:
    """La fuente mezcla 'dd/mm/yyyy' y 'dd/mm/yy' entre temporadas.

    Se normaliza a ISO 'YYYY-MM-DD' porque en ese formato el orden alfabético
    y el orden cronológico son el mismo, y todo el backtest walk-forward
    depende de poder ordenar por fecha sin ambigüedad.
    """
    raw = (raw or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_kickoff(date_iso: str, raw_time: str | None) -> str | None:
    """La hora solo existe desde la temporada 2019/20. Si no está, queda NULL:
    inventarla sería peor que no tenerla."""
    raw_time = (raw_time or "").strip()
    if not date_iso or not raw_time:
        return None
    try:
        t = dt.datetime.strptime(raw_time, "%H:%M").time()
    except ValueError:
        return None
    return f"{date_iso}T{t.isoformat(timespec='minutes')}"


def make_match_id(league: str, date_iso: str, home: str, away: str) -> str:
    """Determinístico: el mismo partido siempre produce el mismo id, aunque se
    re-ingeste desde cero. Eso es lo que hace idempotente a la ingesta."""
    return f"{league}_{date_iso}_{home}_{away}".replace(" ", "-")


def download_season(season: str, league: str = LEAGUE,
                    raw_dir: Path = RAW_DIR, force: bool = False) -> Path:
    """Baja un CSV a data/raw/ y devuelve la ruta. Si ya está, no lo re-baja.

    El archivo crudo se guarda en disco (fuera del repo, ver .gitignore) para
    poder re-cargar la base sin volver a golpear el servidor de la fuente.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{league}_{season}.csv"
    if dest.exists() and not force:
        return dest
    req = urllib.request.Request(season_url(season, league),
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest


def _clean(value: str | None, col: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        if col in INT_COLS:
            return int(float(value))
        if col in FLOAT_COLS:
            return float(value)
    except ValueError:
        return None
    return value


def rows_from_csv(path: Path, league: str, season: str):
    """Convierte un CSV de la fuente en filas listas para la tabla matches."""
    # utf-8-sig: el archivo trae BOM y sin esto la primera columna se llamaría
    # '﻿Div' y no encontraríamos nada.
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): v for k, v in r.items()}
        date_iso = parse_date(r.get("Date"))
        home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        # Las temporadas traen filas vacías al final del archivo.
        if not date_iso or not home or not away:
            continue

        row = {
            "match_id": make_match_id(league, date_iso, home, away),
            "league": league,
            "season": season,
            "match_date": date_iso,
            "kickoff_utc": parse_kickoff(date_iso, r.get("Time")),
            "home_team": home,
            "away_team": away,
            "ingested_at": now,
        }
        for src, col in FIELD_MAP.items():
            row[col] = _clean(r.get(src), col)
        yield row


def upsert_matches(con, rows) -> int:
    cols = ["match_id", "league", "season", "match_date", "kickoff_utc",
            "home_team", "away_team", "fthg", "ftag", "ftr",
            "hc", "ac", "hy", "ay", "hr", "ar", "hs", "as", "hst", "ast",
            "referee", "psch", "pscd", "psca", "ingested_at"]
    # "as" es palabra reservada en SQL; entre comillas dobles SQLite la acepta
    # como nombre de columna.
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f'"{c}" = excluded."{c}"' for c in cols
                        if c != "match_id")
    sql = (f"INSERT INTO matches ({quoted}) VALUES ({placeholders}) "
           f"ON CONFLICT(match_id) DO UPDATE SET {updates}")
    n = 0
    for row in rows:
        con.execute(sql, row)
        n += 1
    con.commit()
    return n


def ingest_all(con, seasons=SEASONS, league: str = LEAGUE, force: bool = False):
    """Baja y carga todas las temporadas del alcance. Devuelve un resumen."""
    summary = []
    for season in seasons:
        path = download_season(season, league, force=force)
        n = upsert_matches(con, rows_from_csv(path, league, season))
        summary.append((season, n, path.stat().st_size))
    return summary
