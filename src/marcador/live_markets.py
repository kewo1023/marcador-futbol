"""Mercados en vivo ademas del 1X2: tarjetas amarillas y goles over/under 2.5.

Es la F5 puesta a emitir. 08_markets.py midio cuatro mercados en backtest y
concluyo que solo tarjetas le gana a la frecuencia base de forma concluyente;
esto toma ese motor, ese encogimiento y ese `w`, y los aplica a los partidos
que vienen, con las mismas reglas que el 1X2: solo datos anteriores al
kickoff, prediccion inmutable, y registro en el ledger.

DOS MODELOS POR PARTIDO, A PROPOSITO
------------------------------------
Cada partido y linea sale con dos filas-modelo: el encogido (produccion) y la
frecuencia base pelada. La base no es relleno: es la UNICA referencia que
existe para tarjetas, porque la fuente no publica cuota. Emitirla como un
modelo mas —con su model_version, sus outcomes y su prob— es lo que permite
que 05_score la evalue con el mismo codigo y que el dashboard diga "modelo
contra base" sin un calculo aparte que nadie pueda auditar desde el ledger.

QUE ES 'BASE' EN VIVO
---------------------
La frecuencia de over sobre TODO lo jugado en esa liga antes del primer
partido a predecir, con el dato de tarjetas presente. 08_markets usaba las
temporadas anteriores a la del partido; aqui, dentro de una temporada en
curso, 'anterior a la fecha' es la version de eso que respeta la regla 4.
"""
import datetime as dt

from . import dixon_coles as dc
from .backtest import ModelConfig
from .config import BASE_MODEL_VERSION, LIVE_MARKETS
from .markets import BY_KEY, market_code

OUTCOMES_OU = ("OVER", "UNDER")


def market_version(cfg: ModelConfig, key: str) -> str:
    """El nombre con el que este mercado firma en el ledger.

    La capa de recalibracion no aplica a ningun mercado over/under, y rho solo
    a goles (Market.use_rho), asi que ninguno de estos modelos ES el campeon
    del 1X2 ni puede llevar su nombre. Es el mismo motor con el rho que le
    toca, mas el sufijo del encogimiento de ese mercado.
    """
    base = ModelConfig(xi=cfg.xi, reg=cfg.reg, use_rho=BY_KEY[key].use_rho,
                       refit_days=cfg.refit_days)
    return f"{base.slug()}+{LIVE_MARKETS[key]['version_suffix']}"


def training_rows(con, league, key, before: dt.date):
    """Lo jugado antes de `before` con el dato del mercado presente."""
    m = BY_KEY[key]
    rows = con.execute(
        f'''SELECT match_date, home_team, away_team,
                   "{m.home_col}" AS hg, "{m.away_col}" AS ag
            FROM matches
            WHERE league = ? AND ftr IS NOT NULL AND match_date < ?
              AND "{m.home_col}" IS NOT NULL AND "{m.away_col}" IS NOT NULL
            ORDER BY match_date''', (league, before.isoformat())).fetchall()
    return [{"date": dt.date.fromisoformat(r["match_date"]),
             "home": r["home_team"], "away": r["away_team"],
             "hg": r["hg"], "ag": r["ag"]} for r in rows]


def base_rates(train, lines):
    """Frecuencia de OVER por linea, sobre el historial dado."""
    n = len(train)
    return {line: sum(1 for t in train if t["hg"] + t["ag"] > line) / n
            for line in lines} if n else {}


def predict(con, league, key, fixtures, cfg: ModelConfig, now_iso):
    """Filas para el ledger: modelo encogido y base, por partido y linea.

    Devuelve ([], None) si no hay historial con el dato. Un partido cuyo
    equipo el ajuste no conoce se salta con aviso: predecirlo daria la media
    de la liga disfrazada de prediccion.
    """
    spec = LIVE_MARKETS[key]
    lines, w = spec["lines"], spec["w"]
    first = dt.date.fromisoformat(min(f["match_date"] for f in fixtures))
    train = training_rows(con, league, key, first)
    if not train:
        return [], None
    fit = dc.fit(train, first, xi=cfg.xi, use_rho=BY_KEY[key].use_rho,
                 reg=cfg.reg)
    cutoff = max(t["date"] for t in train).isoformat()
    base = base_rates(train, lines)
    version = market_version(cfg, key)

    rows, skipped = [], []
    for f in fixtures:
        if not fit.knows(f["home_team"]) or not fit.knows(f["away_team"]):
            skipped.append(f)
            continue
        for line in lines:
            raw = fit.probs_over_under_line(f["home_team"], f["away_team"], line)
            b = base[line]
            shrunk = w[line] * raw["OVER"] + (1 - w[line]) * b
            for mv, p_over in ((version, shrunk), (BASE_MODEL_VERSION, b)):
                for outcome, p in (("OVER", p_over), ("UNDER", 1 - p_over)):
                    rows.append({
                        "match_id": f["match_id"], "match_date": f["match_date"],
                        "home_team": f["home_team"], "away_team": f["away_team"],
                        "model_version": mv, "market": market_code(BY_KEY[key], line),
                        "outcome": outcome, "prob": f"{p:.6f}", "mode": "live",
                        "info_cutoff": cutoff, "created_at": now_iso})
    return rows, {"version": version, "cutoff": cutoff, "base": base,
                  "n_train": len(train), "skipped": skipped}


def parse_market(code: str):
    """'TARJETAS_OU35' -> ('tarjetas', 3.5). None si no es over/under."""
    if "_OU" not in code:
        return None
    key, tail = code.split("_OU", 1)
    try:
        return key.lower(), int(tail) / 10
    except ValueError:
        return None


def actual_outcome(total, line):
    return "OVER" if total > line else "UNDER"


def actual_total(key: str, result_row) -> int | None:
    """El total real del evento en una fila de results.csv, o None si falta.

    Goles salen del marcador, que siempre esta; tarjetas de `yellows`, que se
    guarda aparte y puede faltar en filas anteriores a esa columna.
    """
    if key == "goles":
        try:
            return int(result_row["fthg"]) + int(result_row["ftag"])
        except (KeyError, TypeError, ValueError):
            return None
    if key == "tarjetas":
        v = result_row.get("yellows", "")
        return int(v) if v not in ("", None) else None
    return None
