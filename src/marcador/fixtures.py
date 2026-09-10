"""Proveedor de proximos partidos: fixturedownload.com.

POR QUE ES UN MODULO APARTE DE ingest.py
----------------------------------------
El historico y los resultados vienen de football-data.co.uk y van a seguir
viniendo de ahi: es quien publica las cuotas de cierre, y esas cuotas son el
techo contra el que se mide todo el proyecto. Los proximos partidos vienen de
otro sitio desde el 2026-09-10, y pueden volver a cambiar de sitio —esta
fuente no publica terminos de uso, asi que es un puente—. Separar las dos
cosas es lo que hace que ese cambio sea reemplazar una funcion y no reescribir
la ingesta.

Todo lo que sale de aqui habla el vocabulario de football-data.co.uk: mismos
nombres de equipo (aliases.py), mismo match_id (ingest.make_match_id), misma
tabla. Quien consume las filas no sabe de donde salieron, y asi debe seguir.

QUE ES 'SALUD' PARA ESTA FUENTE
-------------------------------
La anterior era una foto de tres dias, y la pregunta era cuando se tomo. Esta
es la temporada completa, y el archivo puede pasar dias sin cambiar de forma
legitima. La pregunta ahora es otra: los partidos que vienen en los proximos
dias, ¿tienen hora confirmada? La fuente escribe 00:00 cuando la liga no la ha
publicado, y esa marca es la unica senal de que algo se esta quedando atras.
"""
import csv
import datetime as dt
import email.utils
import io
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .aliases import FIXTUREDOWNLOAD, UnknownTeam, canonical
from .config import (CURRENT_SEASON, FIXTURE_SOURCES, FIXTURES_BASE_URL,
                     FIXTURES_LOOKAHEAD_DAYS, RAW_DIR, USER_AGENT)
from .ingest import FIELD_MAP, make_match_id


@dataclass(frozen=True)
class FixtureFile:
    league: str
    path: Path
    last_modified: dt.datetime | None
    fetched_at: dt.datetime

    @property
    def age_hours(self) -> float | None:
        if self.last_modified is None:
            return None
        return (self.fetched_at - self.last_modified).total_seconds() / 3600


@dataclass
class FixturesSnapshot:
    """Los cinco archivos, mas todo lo que se salto y por que."""
    files: dict[str, FixtureFile] = field(default_factory=dict)
    # (liga, nombre) que la tabla de alias no reconocio. Cada uno es un partido
    # que NO se predijo; 05_score.py lo va a reportar cuando se juegue.
    unknown: list[tuple[str, str]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)   # liga -> que fallo

    def path(self, league: str) -> Path | None:
        f = self.files.get(league)
        return f.path if f else None


def _fetch(league: str, raw_dir: Path) -> FixtureFile:
    slug = FIXTURE_SOURCES[league]
    url = f"{FIXTURES_BASE_URL}/{slug}-{_season_year()}-UTC.csv"
    dest = raw_dir / f"fixtures_{league}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
        header = resp.headers.get("Last-Modified")
    last_mod = None
    if header:
        try:
            last_mod = email.utils.parsedate_to_datetime(header)
            if last_mod.tzinfo is None:
                last_mod = last_mod.replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            last_mod = None
    return FixtureFile(league=league, path=dest, last_modified=last_mod,
                       fetched_at=dt.datetime.now(dt.timezone.utc))


def _season_year() -> str:
    """'2627' -> '2026'. La fuente nombra los archivos por el ano de inicio."""
    return f"20{CURRENT_SEASON[:2]}"


def download_all(raw_dir: Path = RAW_DIR,
                 leagues=tuple(FIXTURE_SOURCES)) -> FixturesSnapshot:
    """Baja un archivo por liga. Una liga que falle no para a las demas: se
    anota en `errors` y el resto sigue."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    snap = FixturesSnapshot()
    for lg in leagues:
        try:
            snap.files[lg] = _fetch(lg, raw_dir)
        except Exception as exc:                      # noqa: BLE001
            snap.errors[lg] = f"{type(exc).__name__}: {exc}"[:120]
    return snap


def _parse(path: Path):
    """Filas crudas del archivo, con la fecha ya interpretada.

    Formato observado: 'Match Number,Round Number,Date,Location,Home Team,
    Away Team,Result', con Date como 'dd/mm/yyyy HH:MM' en UTC. Cualquier
    fila que no encaje se salta: un formato que cambia tiene que fallar
    ruidosamente en el conteo, no en silencio dentro de una prediccion.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        try:
            when = dt.datetime.strptime(r["Date"], "%d/%m/%Y %H:%M")
        except (KeyError, ValueError):
            continue
        when = when.replace(tzinfo=dt.timezone.utc)
        yield {"when": when, "home": r.get("Home Team", ""),
               "away": r.get("Away Team", ""), "result": r.get("Result", ""),
               "round": r.get("Round Number", "")}


def fixture_rows(snap: FixturesSnapshot, league: str):
    """Los partidos POR JUGAR de una liga, listos para `ingest.upsert_fixtures`.

    Cada fila sale con los nombres canonicos y el mismo match_id que va a tener
    el resultado cuando llegue por football-data.co.uk. Un nombre que la tabla
    no reconozca salta el partido y lo anota en `snap.unknown`; no se adivina
    nunca, porque una prediccion con el id equivocado es inmutable y huerfana.

    La fecha del partido es la fecha UTC. Se comprobo sobre 99 partidos ya
    jugados que coincide con la que guarda football-data.co.uk en todos.
    """
    path = snap.path(league)
    if path is None:
        return
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for r in _parse(path):
        if r["result"]:
            continue                          # ya se jugo: eso viene del historico
        try:
            home = canonical(FIXTUREDOWNLOAD, league, r["home"])
            away = canonical(FIXTUREDOWNLOAD, league, r["away"])
        except UnknownTeam:
            for name in (r["home"], r["away"]):
                if name not in FIXTUREDOWNLOAD[league] and (league, name) not in snap.unknown:
                    snap.unknown.append((league, name))
            continue
        when = r["when"]
        date_iso = when.date().isoformat()
        # 00:00 es 'la liga no ha confirmado la hora', no medianoche. Se deja
        # en NULL, igual que hacia parse_kickoff: inventarla seria peor.
        confirmed = not (when.hour == 0 and when.minute == 0)
        row = {
            "match_id": make_match_id(league, date_iso, home, away),
            "league": league, "season": CURRENT_SEASON, "match_date": date_iso,
            "kickoff_utc": (when.strftime("%Y-%m-%dT%H:%M") if confirmed else None),
            "home_team": home, "away_team": away,
            "referee": None, "ingested_at": now,
        }
        for col in FIELD_MAP.values():
            row.setdefault(col, None)
        yield row


def health(snap: FixturesSnapshot, today: dt.date,
           lookahead_days: int = FIXTURES_LOOKAHEAD_DAYS) -> dict:
    """Por liga: cuantos partidos vienen en la ventana y cuantos sin hora.

    Es lo que el log imprime siempre, haya predicciones o no. Sustituye al
    'cuando se escribio la foto' de la fuente anterior, que aqui no significa
    nada: el archivo de una temporada entera cambia cuando cambia algo, y
    puede no cambiar en dias sin que eso sea un fallo.
    """
    out = {}
    horizon = today + dt.timedelta(days=lookahead_days)
    for lg, f in snap.files.items():
        n = unconfirmed = 0
        first = last = None
        for r in _parse(f.path):
            if r["result"]:
                continue
            d = r["when"].date()
            first = d if first is None or d < first else first
            last = d if last is None or d > last else last
            if today <= d <= horizon:
                n += 1
                if r["when"].hour == 0 and r["when"].minute == 0:
                    unconfirmed += 1
        out[lg] = {"upcoming": n, "unconfirmed": unconfirmed,
                   "first": first, "last": last, "age_hours": f.age_hours}
    return out
