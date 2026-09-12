"""Cuotas PRE-partido: lo que el mercado opinaba antes del kickoff.

POR QUE EXISTE
--------------
Hasta el 2026-09-12 el mercado solo entraba al ledger DESPUES del partido, con
la cuota de cierre en results.csv. El dashboard podia decir "el modelo puso
49% y el mercado 44%" solo cuando ya se sabia el resultado. Esto registra la
opinion del mercado ANTES, en el mismo momento en que el sistema emite o
revisa sus predicciones, y deja el movimiento de la linea como una serie.

DE DONDE SALE
-------------
Del archivo `fixtures.csv` de football-data.co.uk: la fuente ANTERIOR de
proximos partidos, que dejo de usarse para eso el 2026-09-10 porque su foto
se congela (49 h aquel dia). Para las cuotas sigue sirviendo por dos razones:
es la unica gratuita con el promedio de casas pre-partido, y habla el mismo
vocabulario que el historico — el match_id cae directo, sin alias.

Que se congele a ratos aqui es un hueco tolerable, no una jornada perdida:
un partido sin pre-partido sigue prediciendose y evaluandose igual.

QUE SE GUARDA
-------------
Probabilidades implicitas sin margen (derivadas, regla 2), no la cuota, y
NUNCA la de una casa concreta: el promedio (`Avg*`). Si el archivo no lo trae
para un partido, ese partido queda sin fila. Se agrega una fila solo cuando
la opinion del mercado CAMBIO respecto a la ultima registrada: seis corridas
al dia sobre un archivo que no se regenero no son seis datos, son uno.

QUE NO ES
---------
No es una feature del modelo. Meterle la cuota al modelo lo convierte en un
seguidor del mercado y destruye la pregunta del proyecto. Y no es una
senal de apuesta: una diferencia de 5 puntos entre el modelo y el mercado es,
por ahora, evidencia de que el modelo se equivoca (regla 6, +0.0230 de
brecha en backtest), no de que el mercado se equivoque.
"""
import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .config import LEAGUES, RAW_DIR
from .ingest import FixturesSnapshot, download_fixtures, make_match_id, parse_date

@dataclass(frozen=True)
class PreMatch:
    match_id: str
    match_date: str
    home_team: str
    away_team: str
    probs_1x2: dict | None        # {"H":..,"D":..,"A":..} sin margen, o None
    probs_ou25: dict | None       # {"OVER":..,"UNDER":..} sin margen, o None


def fetch(raw_dir: Path = RAW_DIR) -> FixturesSnapshot:
    """Baja el archivo. Devuelve la foto con su Last-Modified: la fecha en que
    la fuente lo escribio es la que dice si la cuota es de antes del partido."""
    return download_fixtures(raw_dir)


def _odds(r, *cols):
    vals = []
    for c in cols:
        try:
            v = float((r.get(c) or "").strip())
        except ValueError:
            return None
        if v <= 1.0:
            return None
        vals.append(v)
    return vals


def _no_margin(odds, keys):
    inv = [1 / o for o in odds]
    total = sum(inv)
    return {k: v / total for k, v in zip(keys, inv)}


def rows(snap: FixturesSnapshot, leagues=LEAGUES):
    """Lee el archivo y devuelve un PreMatch por partido de nuestras ligas."""
    text = snap.path.read_text(encoding="utf-8-sig", errors="replace")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "") for k, v in r.items()}
        div = r.get("Div", "").strip()
        if div not in leagues:
            continue
        date_iso = parse_date(r.get("Date"))
        home, away = r.get("HomeTeam", "").strip(), r.get("AwayTeam", "").strip()
        if not date_iso or not home or not away:
            continue
        o1x2 = _odds(r, "AvgH", "AvgD", "AvgA")
        oou = _odds(r, "Avg>2.5", "Avg<2.5")
        out.append(PreMatch(
            match_id=make_match_id(div, date_iso, home, away),
            match_date=date_iso, home_team=home, away_team=away,
            probs_1x2=_no_margin(o1x2, ("H", "D", "A")) if o1x2 else None,
            probs_ou25=_no_margin(oou, ("OVER", "UNDER")) if oou else None))
    return out


def ledger_rows(pre_matches, snap: FixturesSnapshot, only_ids=None,
                fetched_at: str = ""):
    """Filas listas para el ledger. `only_ids` restringe a los partidos que el
    sistema tiene en su ventana (kickoff por delante): asi 'pre' significa
    pre de verdad, no una cuota leida despues del pitazo."""
    modified = (snap.last_modified.isoformat(timespec="seconds")
                if snap.last_modified else "")
    out = []
    for m in pre_matches:
        if only_ids is not None and m.match_id not in only_ids:
            continue
        if not m.probs_1x2 and not m.probs_ou25:
            continue
        p, q = m.probs_1x2 or {}, m.probs_ou25 or {}
        f6 = lambda x: f"{x:.6f}" if x is not None else ""     # noqa: E731
        out.append({"match_id": m.match_id, "match_date": m.match_date,
                    "home_team": m.home_team, "away_team": m.away_team,
                    "pre_h": f6(p.get("H")), "pre_d": f6(p.get("D")),
                    "pre_a": f6(p.get("A")),
                    "pre_o25": f6(q.get("OVER")), "pre_u25": f6(q.get("UNDER")),
                    "file_modified": modified, "fetched_at": fetched_at})
    return out
