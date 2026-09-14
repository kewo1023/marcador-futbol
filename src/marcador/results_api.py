"""Resultados desde football-data.org (API v4): el marcador, en horas.

POR QUE EXISTE
--------------
La fuente oficial (football-data.co.uk) publica una fila completa por
partido —marcador, cuota de cierre, tarjetas, tiros— y por eso es la que
evalua al modelo. Pero la primera jornada en vivo (11–14/09/2026) tardo mas
de una semana en aparecer alli, con 43 partidos predichos esperando. Esta API
da el marcador el mismo dia (medido: los del domingo por la noche estaban a
las 00:20 UTC del lunes).

LO QUE HACE Y LO QUE NO
-----------------------
Trae SOLO el marcador (`score.fullTime`) de los partidos `FINISHED`. Con eso
`05_score` escribe el resultado en el ledger y evalua el 1X2 de inmediato,
contra el mercado pre-partido que ya se guardo antes del kickoff. La cuota
de cierre, las tarjetas y los tiros siguen llegando por football-data.co.uk
y completan la fila despues. Si las dos fuentes discrepan en el marcador,
`ledger.upsert_results` aborta con error: nunca se pisa un resultado.

Los nombres se traducen al vocabulario canonico con `aliases.FOOTBALL_DATA_ORG`
ANTES de construir el match_id, con la misma regla que la otra fuente: un
nombre desconocido salta el partido con aviso, nunca se adivina.

TOKEN
-----
Personal, gratuito, y nunca va al repo: `config.results_api_token()` lo lee
del entorno o de `.env`. Sin token, `05_score` sigue funcionando solo con la
fuente oficial y lo dice.
"""
import datetime as dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .aliases import FOOTBALL_DATA_ORG, UnknownTeam, canonical
from .config import (LEAGUES, RESULTS_API_BASE, RESULTS_API_CODES, USER_AGENT,
                     results_api_token)
from .ingest import make_match_id


class NoToken(RuntimeError):
    pass


@dataclass
class ApiResult:
    match_id: str
    match_date: str
    home_team: str
    away_team: str
    fthg: int
    ftag: int
    ftr: str
    last_updated: str      # cuando la API toco el partido por ultima vez


@dataclass
class ApiSnapshot:
    fetched_at: str
    results: list = field(default_factory=list)      # ApiResult
    errors: dict = field(default_factory=dict)       # liga -> mensaje
    unknown: list = field(default_factory=list)      # (liga, nombre)
    counts: dict = field(default_factory=dict)       # liga -> (traidos, terminados)


def _get(path: str, params: dict, token: str) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{RESULTS_API_BASE}{path}?{qs}",
                                 headers={"X-Auth-Token": token,
                                          "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_finished(date_from: dt.date, date_to: dt.date,
                   leagues=LEAGUES, token: str | None = None) -> ApiSnapshot:
    """Los partidos terminados de nuestras ligas entre dos fechas (dateTo
    excluida por la API; aqui se suma un dia para que sea inclusiva).

    Una liga que falle no para a las otras: queda en `errors`. El plan gratis
    permite 10 llamadas por minuto; aqui son cinco por corrida.
    """
    token = token or results_api_token()
    if not token:
        raise NoToken("No hay FOOTBALL_DATA_TOKEN (entorno o .env).")
    snap = ApiSnapshot(fetched_at=dt.datetime.now(dt.timezone.utc)
                       .isoformat(timespec="seconds"))
    for lg in leagues:
        code = RESULTS_API_CODES[lg]
        try:
            data = _get(f"/competitions/{code}/matches",
                        {"dateFrom": date_from.isoformat(),
                         "dateTo": (date_to + dt.timedelta(days=1)).isoformat()},
                        token)
        except urllib.error.HTTPError as exc:
            snap.errors[lg] = f"HTTP {exc.code}"
            continue
        except Exception as exc:                        # noqa: BLE001
            snap.errors[lg] = str(exc)[:60]
            continue
        n_fin = 0
        for m in data.get("matches", []):
            if m.get("status") != "FINISHED":
                continue
            n_fin += 1
            try:
                home = canonical(FOOTBALL_DATA_ORG, lg, m["homeTeam"]["name"])
                away = canonical(FOOTBALL_DATA_ORG, lg, m["awayTeam"]["name"])
            except UnknownTeam:
                for name in (m["homeTeam"]["name"], m["awayTeam"]["name"]):
                    if name not in FOOTBALL_DATA_ORG[lg] and (lg, name) not in snap.unknown:
                        snap.unknown.append((lg, name))
                continue
            ft = m["score"]["fullTime"]
            if ft.get("home") is None or ft.get("away") is None:
                continue
            hg, ag = int(ft["home"]), int(ft["away"])
            # La fecha del id es la fecha UTC del kickoff, como en fixtures.py.
            date_iso = m["utcDate"][:10]
            snap.results.append(ApiResult(
                match_id=make_match_id(lg, date_iso, home, away),
                match_date=date_iso, home_team=home, away_team=away,
                fthg=hg, ftag=ag, ftr="H" if hg > ag else ("A" if ag > hg else "D"),
                last_updated=m.get("lastUpdated", "")))
        snap.counts[lg] = (len(data.get("matches", [])), n_fin)
    return snap
