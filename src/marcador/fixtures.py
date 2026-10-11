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
from .config import (BREAK_MIN_DAYS, CURRENT_SEASON, FIXTURE_SOURCES,
                     FIXTURES_BASE_URL, FIXTURES_LOOKAHEAD_DAYS, RAW_DIR,
                     USER_AGENT)
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


def provisional_scores(snap: FixturesSnapshot, league: str) -> dict:
    """{match_id: 'hg-ag'} de los partidos que el archivo ya da por jugados.

    ES PROVISIONAL Y NO CUENTA. El resultado que evalua al modelo viene de
    football-data.co.uk, con la cuota de cierre, tarjetas y tiros en la misma
    fila, y ese tarda dias en publicarse (una semana entera la del 11/09).
    Esto existe para que, mientras tanto, el dashboard pueda mostrar que paso
    en vez de un guion. No entra a results.csv ni a metrics.csv: una sola
    verdad para lo que cuenta, y una vista previa para lo que se espera.
    """
    path = snap.path(league)
    if path is None:
        return {}
    out = {}
    for r in _parse(path):
        if not r["result"]:
            continue
        try:
            hg, ag = (int(x) for x in r["result"].split("-"))
        except ValueError:
            continue                          # formato raro: mejor sin dato
        try:
            home = canonical(FIXTUREDOWNLOAD, league, r["home"])
            away = canonical(FIXTUREDOWNLOAD, league, r["away"])
        except UnknownTeam:
            continue                          # ya lo anoto fixture_rows
        date_iso = r["when"].date().isoformat()
        out[make_match_id(league, date_iso, home, away)] = f"{hg}-{ag}"
    return out


def rescheduled(snap: FixturesSnapshot, league: str, candidates) -> list[dict]:
    """De los partidos `candidates` (predichos, kickoff pasado, sin resultado),
    los que el archivo de la temporada tiene en OTRA fecha.

    Es determinista porque en una liga cada (local, visitante) se juega una
    sola vez por temporada: si el archivo trae ese cruce en otro dia, el
    partido se movio. Se exige que aparezca exactamente una vez; con cero (la
    liga lo saco sin fecha nueva) o con mas de una no se concluye nada, y el
    partido sigue contando como "esperando resultado", que es lo honesto.

    `candidates`: dicts con match_id, home_team, away_team (vocabulario
    canonico, el del ledger) y kickoff_utc (la hora con que se predijo, o
    vacia). Devuelve old_match_id, old_kickoff_utc, new_match_id y
    new_kickoff_utc (None si la liga no confirmo la hora).
    """
    path = snap.path(league)
    if path is None or not candidates:
        return []
    by_pair = {}
    for r in _parse(path):
        try:
            pair = (canonical(FIXTUREDOWNLOAD, league, r["home"]),
                    canonical(FIXTUREDOWNLOAD, league, r["away"]))
        except UnknownTeam:
            continue                          # ya lo anoto fixture_rows
        by_pair.setdefault(pair, []).append(r["when"])
    out = []
    for c in candidates:
        whens = by_pair.get((c["home_team"], c["away_team"]), [])
        if len(whens) != 1:
            continue
        when = whens[0]
        new_id = make_match_id(league, when.date().isoformat(),
                               c["home_team"], c["away_team"])
        if new_id == c["match_id"]:
            continue                          # misma fecha: no se movio
        confirmed = not (when.hour == 0 and when.minute == 0)
        out.append({"old_match_id": c["match_id"],
                    "old_kickoff_utc": c.get("kickoff_utc") or "",
                    "new_match_id": new_id,
                    "new_kickoff_utc": (when.strftime("%Y-%m-%dT%H:%M")
                                        if confirmed else None)})
    return out


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


# --- Parones ------------------------------------------------------------------
# El archivo de cada liga es la temporada ENTERA, jugados y por jugar. Eso
# quiere decir que el sistema sabe desde agosto cuando no va a haber partidos.
# Hasta el 2026-10-11 no lo usaba: una triple fecha FIFA dejo 19 dias sin
# predicciones y la lectura fue "algo se rompio", cuando el calendario lo
# decia. Un hueco que la fuente anuncia no es un fallo; uno que no anuncia, si.

def season_dates(snap: FixturesSnapshot) -> dict:
    """{liga: [fechas con partido]} de toda la temporada, ordenadas."""
    return {lg: sorted({r["when"].date() for r in _parse(f.path)})
            for lg, f in snap.files.items()}


def breaks(dates, min_days: int = BREAK_MIN_DAYS):
    """[(ultimo dia con partido, siguiente dia con partido)] de cada hueco de
    `min_days` o mas entre dos fechas consecutivas."""
    return [(a, b) for a, b in zip(dates, dates[1:]) if (b - a).days >= min_days]


def calendar_rows(snap: FixturesSnapshot, computed_at: str = "",
                  min_days: int = BREAK_MIN_DAYS):
    """Filas para ledger/calendar.csv: los parones de cada liga y los de las
    cinco juntas (ALL), que es la firma de una fecha FIFA.

    ALL solo se calcula si bajaron todas las ligas: con una que falte, un
    hueco de las demas pareceria general sin serlo.
    """
    by_lg = season_dates(snap)
    out = []
    for lg in sorted(by_lg):
        for a, b in breaks(by_lg[lg], min_days):
            out.append(_break_row(lg, a, b, computed_at))
    if by_lg and not snap.errors:
        union = sorted(set().union(*by_lg.values()))
        for a, b in breaks(union, min_days):
            out.append(_break_row("ALL", a, b, computed_at))
    return out


def _break_row(league, a, b, computed_at):
    return {"league": league, "last_match": a.isoformat(),
            "next_match": b.isoformat(), "idle_days": str((b - a).days - 1),
            "computed_at": computed_at}


def break_at(calendar, league: str, day: dt.date):
    """La fila del paron que cubre `day` para esa liga (o ALL), o None.

    `calendar` son filas de ledger/calendar.csv. Un dia 'esta en paron' si
    cae estrictamente entre el ultimo partido y el siguiente.
    """
    iso = day.isoformat()
    for r in calendar:
        if r["league"] == league and r["last_match"] < iso < r["next_match"]:
            return r
    return None
