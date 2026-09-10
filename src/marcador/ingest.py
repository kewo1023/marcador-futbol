"""Ingesta: baja los CSV de la fuente y los carga a SQLite.

Es idempotente. Correrlo dos veces no duplica partidos: cada partido tiene un
match_id determinístico y se usa INSERT ... ON CONFLICT DO UPDATE.
"""
import csv
import datetime as dt
import email.utils
import io
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import LEAGUE, RAW_DIR, SEASONS, USER_AGENT, season_url

# Columnas de la fuente -> columnas de la tabla. Lo que no esté aquí se ignora.
FIELD_MAP = {
    "FTHG": "fthg", "FTAG": "ftag", "FTR": "ftr",
    "HC": "hc", "AC": "ac",
    "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar",
    "HS": "hs", "AS": "as", "HST": "hst", "AST": "ast",
    "Referee": "referee",
    "AvgH": "avgh", "AvgD": "avgd", "AvgA": "avga",
    "MaxH": "maxh", "MaxD": "maxd", "MaxA": "maxa",
    "MaxCH": "maxch", "MaxCD": "maxcd", "MaxCA": "maxca",
    "AvgCH": "avgch", "AvgCD": "avgcd", "AvgCA": "avgca",
    "AvgC>2.5": "avgc_o25", "AvgC<2.5": "avgc_u25",
    "PSCH": "psch", "PSCD": "pscd", "PSCA": "psca",
}
INT_COLS = {"fthg", "ftag", "hc", "ac", "hy", "ay", "hr", "ar",
            "hs", "as", "hst", "ast"}
FLOAT_COLS = {"avgh", "avgd", "avga", "maxh", "maxd", "maxa",
              "maxch", "maxcd", "maxca",
              "avgch", "avgcd", "avgca", "avgc_o25", "avgc_u25",
              "psch", "pscd", "psca"}


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
            "referee", "avgh", "avgd", "avga", "maxh", "maxd", "maxa",
            "maxch", "maxcd", "maxca",
            "avgch", "avgcd", "avgca", "avgc_o25", "avgc_u25",
            "psch", "pscd", "psca", "ingested_at"]
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
    """Baja y carga todas las temporadas de UNA liga. Devuelve un resumen."""
    summary = []
    for season in seasons:
        path = download_season(season, league, force=force)
        n = upsert_matches(con, rows_from_csv(path, league, season))
        summary.append((season, n, path.stat().st_size))
    return summary


def ingest_leagues(con, leagues, seasons=SEASONS, force: bool = False):
    """Todas las ligas del alcance. Devuelve {liga: [(temporada, n, bytes)]}.

    Una temporada que no exista para una liga (o que venga vacia) se salta sin
    romper: las ligas no comparten calendario ni antiguedad de datos.
    """
    out = {}
    for league in leagues:
        rows = []
        for season in seasons:
            try:
                path = download_season(season, league, force=force)
                n = upsert_matches(con, rows_from_csv(path, league, season))
            except Exception as exc:            # noqa: BLE001
                rows.append((season, 0, 0, str(exc)[:40]))
                continue
            rows.append((season, n, path.stat().st_size, ""))
        out[league] = rows
    return out


# --- Partidos por jugar (fuente ANTERIOR: football-data.co.uk) ---------------
#
# FUERA DE PRODUCCION desde el 2026-09-10. Los proximos partidos vienen ahora
# de fixtures.py (fixturedownload.com, temporada completa). Esto se conserva
# entero para poder volver a medir la fuente anterior —su foto de tres dias y
# cuando la regenera— sin reconstruirlo, y porque el detector de frescura que
# hay aqui es el que dejo claro por que habia que cambiar.

@dataclass(frozen=True)
class FixturesSnapshot:
    """El archivo de proximos partidos, con lo que se sabe de su frescura.

    `download_fixtures` devolvia solo la ruta, y con la ruta sola no hay forma
    de distinguir un archivo recien escrito de uno congelado hace tres dias:
    los dos se leen igual y los dos producen cero partidos cuando la jornada
    cae fuera de la foto. El `last-modified` de la respuesta es el unico dato
    que separa los dos casos, y se estaba tirando.
    """
    path: Path
    last_modified: dt.datetime | None
    fetched_at: dt.datetime

    @property
    def age_hours(self) -> float | None:
        """Horas desde que la fuente escribio el archivo. None si no lo dice."""
        if self.last_modified is None:
            return None
        return (self.fetched_at - self.last_modified).total_seconds() / 3600

    @property
    def is_stale(self) -> bool:
        """Sin cabecera se asume rancio: no poder comprobarlo no es estar bien."""
        from .config import FIXTURES_STALE_HOURS
        age = self.age_hours
        return age is None or age > FIXTURES_STALE_HOURS

    def describe(self) -> str:
        if self.last_modified is None:
            return "la fuente no dice cuando escribio el archivo"
        stamp = self.last_modified.strftime("%Y-%m-%d %H:%M UTC")
        return f"escrito {stamp}, hace {self.age_hours:.0f} h"


def download_fixtures(raw_dir: Path = RAW_DIR) -> FixturesSnapshot:
    """Baja el archivo de proximos partidos. Siempre se re-baja: es el unico
    dato que cambia de un dia para otro.

    Devuelve un FixturesSnapshot, no una ruta: quien lo use necesita saber si
    el archivo esta fresco tanto como necesita leerlo.
    """
    from .config import FIXTURES_URL
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / "fixtures.csv"
    req = urllib.request.Request(FIXTURES_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
        header = resp.headers.get("Last-Modified")
    last_mod = None
    if header:
        try:
            last_mod = email.utils.parsedate_to_datetime(header)
            if last_mod.tzinfo is None:                 # RFC 2822 sin zona
                last_mod = last_mod.replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            last_mod = None                             # cabecera malformada
    return FixturesSnapshot(path=dest, last_modified=last_mod,
                            fetched_at=dt.datetime.now(dt.timezone.utc))


def fixtures_summary(path: Path) -> dict:
    """Que ligas y que rango de fechas trae el archivo, sin filtrar por liga.

    Existe para que el log pueda responder «por que no esta mi partido» sin que
    nadie tenga que bajar el archivo a mano: si trae seis ligas y ninguna es la
    nuestra, eso se ve de un vistazo.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    leagues, dates = {}, []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): v for k, v in r.items()}
        div = (r.get("Div") or "").strip()
        if not div:
            continue
        leagues[div] = leagues.get(div, 0) + 1
        iso = parse_date(r.get("Date"))
        if iso:
            dates.append(iso)
    return {"leagues": leagues, "n": sum(leagues.values()),
            "first": min(dates) if dates else None,
            "last": max(dates) if dates else None}


def fixture_rows(path: Path, league: str = LEAGUE, season: str | None = None):
    """Los proximos partidos de nuestra liga, con formato de fila de `matches`.

    Van a la MISMA tabla que los partidos jugados, con el resultado en NULL.
    Es a proposito: el match_id es deterministico a partir de fecha y equipos,
    asi que cuando el resultado llegue caera sobre la misma fila y la
    prediccion que ya se emitio quedara conectada sola.

    El archivo es una FOTO que la fuente regenera cada cierto tiempo, no una
    ventana que rueda con el dia, y trae todas las ligas juntas. Que no traiga
    ninguna fila de las nuestras significa que su jornada cae fuera de esa foto,
    no que no se juegue.

    Medido el 2026-09-10 a las 03:12 UTC: last-modified del martes 08/09 18:07
    UTC, cubriendo del 08 al 10 de septiembre — 34 horas sin regenerarse, con
    la jornada de las cinco ligas arrancando el 11.

    Que la foto este fresca lo comprueba `FixturesSnapshot.is_stale` ANTES del
    kickoff; que ninguna jornada se haya caido lo comprueba 05_score.py
    DESPUES. Ninguna de las dos cosas se asume.
    """
    from .config import CURRENT_SEASON
    season = season or CURRENT_SEASON
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): v for k, v in r.items()}
        if (r.get("Div") or "").strip() != league:
            continue
        date_iso = parse_date(r.get("Date"))
        home = (r.get("HomeTeam") or "").strip()
        away = (r.get("AwayTeam") or "").strip()
        if not date_iso or not home or not away:
            continue
        row = {
            "match_id": make_match_id(league, date_iso, home, away),
            "league": league, "season": season, "match_date": date_iso,
            "kickoff_utc": parse_kickoff(date_iso, r.get("Time")),
            "home_team": home, "away_team": away,
            "referee": _clean(r.get("Referee"), "referee"),
            "ingested_at": now,
        }
        # Todo lo demas queda en None: el partido no se ha jugado.
        for col in FIELD_MAP.values():
            row.setdefault(col, None)
        yield row


def upsert_fixtures(con, rows) -> int:
    """Inserta partidos por jugar SIN pisar un resultado ya registrado.

    El DO NOTHING importa: si el partido ya se jugo y se ingesto, volver a
    verlo en el archivo de fixtures no puede borrar su marcador.
    """
    cols = ["match_id", "league", "season", "match_date", "kickoff_utc",
            "home_team", "away_team", "referee", "ingested_at"]
    quoted = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    sql = (f"INSERT INTO matches ({quoted}) VALUES ({placeholders}) "
           f"ON CONFLICT(match_id) DO NOTHING")
    n = 0
    for row in rows:
        cur = con.execute(sql, {c: row[c] for c in cols})
        n += cur.rowcount
    con.commit()
    return n
