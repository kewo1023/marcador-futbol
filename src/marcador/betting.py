"""El tablero de decision: si apostar, a que precio, y cuanto se habria ganado.

POR QUE EXISTE
--------------
La pregunta "¿a que le apuesto esta jornada?" tiene una respuesta que el
proyecto ya sabia dar y que no se veia: la F7 (09_value.py) midio que el filtro
de valor pierde dinero con cuotas reales, y el bootstrap en vivo (14) dice que
el modelo no le gana al mercado. Este modulo convierte esas mediciones en una
decision por mercado, y mide en vivo cualquier regla de apuesta antes de que
cueste un peso.

LAS TRES PIEZAS
---------------
1. Semaforo por mercado. Bootstrap pareado del modelo contra el mercado
   (regla 6), contra el cierre y contra el pre-partido. Verde solo si le gana
   de forma concluyente y ninguna referencia dice lo contrario. Sin verde, la
   recomendacion es no apostar, diga lo que diga una probabilidad suelta.
2. Cuota minima. 1 / probabilidad del modelo: por debajo de esa cuota la
   apuesta pierde dinero aunque el modelo tenga razon. Es lo unico accionable
   cuando se mira la casa de apuestas.
3. Paper trading. Reglas de apuesta aplicadas a lo que el ledger ya tiene
   (prediccion inmutable + ultima linea del mercado antes del kickoff), sin
   dinero. Se deriva, no se escribe: las dos entradas ya son de antes del
   partido y estan versionadas, asi que el resultado es auditable y no hace
   falta un archivo nuevo que solo el runner pueda tocar (regla 8).

QUE NO ES
---------
No es una feature del modelo ni cambia ninguna prediccion. Y "probabilidad
alta" no es "buena apuesta": el favorito al 80 % ya lo paga la casa a 1.20.
La regla "las 10 mas probables" (un solo lado por partido y mercado) se mide
aqui como una estrategia mas, no se recomienda.
"""
import datetime as dt

from . import live_markets, scoring

# Los unicos mercados con precio en la fuente. Tarjetas y tiros no tienen
# cuota: el modelo le gana a la base, pero no hay forma de saber si a la casa.
PRE_COLS = {
    "1X2": {"H": "pre_h", "D": "pre_d", "A": "pre_a"},
    "GOLES_OU25": {"OVER": "pre_o25", "UNDER": "pre_u25"},
}
CLOSE_COLS = {
    "1X2": {"H": "market_h", "D": "market_d", "A": "market_a"},
    "GOLES_OU25": {"OVER": "market_o25", "UNDER": "market_u25"},
}
PRICED_MARKETS = tuple(PRE_COLS)

# Margen de las casas sobre el promedio de cuotas, medido el 2026-10-11 en la
# base de las cinco ligas: 6.4 % (25/26) y 6.5 % (26/27) en el 1X2, 6.5 % y
# 6.6 % en goles 2.5. El ledger guarda la probabilidad sin margen (regla 2: no
# la cuota), asi que la cuota que pagaba la casa se reconstruye aproximada:
# cuota_justa / (1 + margen). Es aproximada porque el margen real varia por
# partido y carga mas a los no favoritos.
TYPICAL_MARGIN = 0.065

# Por debajo de esto el bootstrap no se corre (mismo umbral que live_paired).
MIN_MATCHES = 30


# --- Entradas ---------------------------------------------------------------

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pre_before_kickoff(market_pre_rows, fixture_rows):
    """{match_id: fila} con la ULTIMA linea del mercado registrada antes del
    kickoff. 04_predict ya solo pide cuotas de partidos por jugar; esto lo
    vuelve a comprobar contra la hora, por si acaso, cuando la hora existe."""
    kickoff = {r["match_id"]: r.get("kickoff_utc") or "" for r in fixture_rows}
    out = {}
    for r in market_pre_rows:
        ko = kickoff.get(r["match_id"], "")
        if ko and r.get("fetched_at", "")[:16] >= ko:
            continue
        out[r["match_id"]] = r
    return out


def actual_outcome(market, result_row):
    """Lo que paso en ese mercado, o None si la fila no trae el dato."""
    if market == "1X2":
        return result_row.get("ftr") or None
    parsed = live_markets.parse_market(market)
    if not parsed:
        return None
    total = live_markets.actual_total(parsed[0], result_row)
    return None if total is None else live_markets.actual_outcome(total, parsed[1])


def jornada(date_iso: str) -> str:
    """La jornada como la semana de martes a lunes: el martes que la abre.

    Las cinco ligas juegan de viernes a lunes, y una fecha entre semana cae en
    la misma semana que el fin de semana siguiente. Con la semana ISO (lunes a
    domingo) el lunes de Premier quedaria en la jornada siguiente.
    """
    d = dt.date.fromisoformat(date_iso)
    return (d - dt.timedelta(days=(d.weekday() - 1) % 7)).isoformat()


def selections(preds, pre, versions):
    """Una fila por (partido, mercado, outcome) del modelo en produccion.

    `versions` es el conjunto de model_version en produccion (una por familia
    de mercados: 1X2, goles, tarjetas, tiros). Las versiones anteriores que
    conviven en el ledger no cuentan. `pre` sale de
    pre_before_kickoff. p_pre es None en mercados sin precio o en partidos sin
    linea registrada.
    """
    by_key = {}
    for p in preds:
        if p.get("mode") != "live" or p["model_version"] not in versions:
            continue
        k = (p["match_id"], p["market"], p["outcome"])
        by_key[k] = p
    out = []
    for (mid, market, outcome), p in by_key.items():
        prob = float(p["prob"])
        row = pre.get(mid)
        col = PRE_COLS.get(market, {}).get(outcome)
        p_pre = _f(row.get(col)) if (row and col) else None
        out.append({
            "match_id": mid, "match_date": p["match_date"],
            "jornada": jornada(p["match_date"]),
            "home_team": p["home_team"], "away_team": p["away_team"],
            "market": market, "outcome": outcome, "p_model": prob,
            "p_pre": p_pre, "min_odds": 1 / prob if prob > 0 else None,
            "edge": (prob - p_pre) if p_pre is not None else None,
        })
    return out


# --- Reglas de apuesta (las que se miden en paper trading) ------------------

def top_by_jornada(sels, n=10, priced_only=True):
    """Las `n` selecciones mas probables de cada jornada. Es la regla que se
    pidio el 2026-10-11, y por eso se mide: no porque se espere que gane.

    Un solo lado por (partido, mercado): el que el modelo ve mas probable.
    Sin esto, con pocos partidos por jugar la lista se llenaba con todas las
    opciones y mostraba a la vez «gana el local» y «gana el visitante» del
    mismo partido (2026-10-26: dos partidos x cinco opciones = las 10). Si
    quedan menos de `n` selecciones, se devuelven las que hay.
    """
    pool = [s for s in sels if s["p_pre"] is not None] if priced_only else list(sels)
    best = {}
    for s in pool:
        k = (s["match_id"], s["market"])
        if k not in best or s["p_model"] > best[k]["p_model"]:
            best[k] = s
    by_j = {}
    for s in best.values():
        by_j.setdefault(s["jornada"], []).append(s)
    out = []
    for j in sorted(by_j):
        out += sorted(by_j[j], key=lambda s: -s["p_model"])[:n]
    return out


def value_picks(sels, min_edge=0.0):
    """Donde el modelo pone mas que el mercado pre-partido. Es la regla que
    la F7 midio en backtest (y perdio); aqui se mide en vivo."""
    return [s for s in sels if s["edge"] is not None and s["edge"] > min_edge]


STRATEGIES = {
    "top10": ("Las 10 más probables de cada jornada", top_by_jornada),
    "valor": ("Valor: modelo > mercado pre-partido", value_picks),
}


# --- Liquidacion y resumen --------------------------------------------------

def settle(bets, results_by_id, margin=TYPICAL_MARGIN):
    """Liquida cada apuesta de 1 unidad que ya tiene resultado.

    pnl_fair: a la cuota sin margen del mercado pre (techo: ninguna casa la
    paga). pnl_net: a esa cuota menos el margen tipico (lo realista).
    clv: probabilidad de cierre menos la tomada. Positivo = el mercado se
    movio hacia la apuesta despues de hacerla, que es la senal mas temprana
    de que se sabe algo (el ROI tarda cientos de apuestas en hablar).
    """
    out = []
    for b in bets:
        r = results_by_id.get(b["match_id"])
        if r is None or b["p_pre"] is None or b["p_pre"] <= 0:
            continue
        actual = actual_outcome(b["market"], r)
        if actual is None:
            continue
        won = actual == b["outcome"]
        fair = 1 / b["p_pre"]
        net = fair / (1 + margin)
        col = CLOSE_COLS.get(b["market"], {}).get(b["outcome"])
        p_close = _f(r.get(col)) if col else None
        out.append({**b, "won": won,
                    "pnl_fair": (fair - 1) if won else -1.0,
                    "pnl_net": (net - 1) if won else -1.0,
                    "clv": (p_close - b["p_pre"]) if p_close is not None else None})
    return out


def _mean_ci(values):
    """(media, lo, hi) con bootstrap (regla 6), o (media, None, None) si hay
    muy pocos valores para que el intervalo signifique algo."""
    if not values:
        return None, None, None
    mean = sum(values) / len(values)
    if len(values) < MIN_MATCHES:
        return mean, None, None
    m, lo, hi, _, _ = scoring.bootstrap_diff(values, [0.0] * len(values))
    return m, lo, hi


def summarize(settled):
    """ROI por unidad apostada (techo y neto) y CLV, cada uno con su IC."""
    roi_fair = _mean_ci([b["pnl_fair"] for b in settled])
    roi_net = _mean_ci([b["pnl_net"] for b in settled])
    clvs = [b["clv"] for b in settled if b["clv"] is not None]
    clv = _mean_ci(clvs)
    return {"n": len(settled),
            "hit_rate": (sum(b["won"] for b in settled) / len(settled)) if settled else None,
            "roi_fair": roi_fair, "roi_net": roi_net,
            "clv": clv, "n_clv": len(clvs)}


def paper_trading(sels, results_by_id):
    """{estrategia: (etiqueta, resumen, apuestas liquidadas)}."""
    out = {}
    for key, (label, rule) in STRATEGIES.items():
        settled = settle(rule(sels), results_by_id)
        out[key] = (label, summarize(settled), settled)
    return out


# --- Semaforo ---------------------------------------------------------------

def _paired_inputs(sels, results_by_id, pre, market):
    """Los diccionarios que espera scoring.live_paired, para el modelo y cada
    referencia, sobre los partidos con resultado."""
    probs = {}
    for s in sels:
        if s["market"] == market:
            probs.setdefault(s["match_id"], {})[s["outcome"]] = s["p_model"]
    n_out = len(PRE_COLS[market])
    model, close, pre_ref = {}, {}, {}
    for mid, p in probs.items():
        r = results_by_id.get(mid)
        if r is None or len(p) != n_out:
            continue
        actual = actual_outcome(market, r)
        if actual is None:
            continue
        model[mid] = {"probs": p, "actual": actual}
        c = {o: _f(r.get(col)) for o, col in CLOSE_COLS[market].items()}
        if all(v is not None for v in c.values()):
            close[mid] = {"probs": c, "actual": actual}
        row = pre.get(mid)
        if row:
            q = {o: _f(row.get(col)) for o, col in PRE_COLS[market].items()}
            if all(v is not None for v in q.values()):
                pre_ref[mid] = {"probs": q, "actual": actual}
    return model, close, pre_ref


def _verdict(res):
    if res is None:
        return "sin datos"
    _, lo, hi, _, _ = res
    if hi < 0:
        return "gana"
    if lo > 0:
        return "pierde"
    return "no concluyente"


def traffic_light(sels, results_by_id, pre, market):
    """Estado del mercado: 'verde', 'amarillo', 'rojo' o 'gris', y el detalle.

    rojo: alguna referencia le gana al modelo de forma concluyente.
    verde: alguna le pierde de forma concluyente y ninguna gana.
    amarillo: nada demostrado en ningun sentido.
    gris: el mercado no tiene precio, o no hay 30 partidos en comun.
    """
    if market not in PRE_COLS:
        return "gris", {}
    model, close, pre_ref = _paired_inputs(sels, results_by_id, pre, market)
    detail = {"cierre": scoring.live_paired(model, close),
              "pre-partido": scoring.live_paired(model, pre_ref)}
    verdicts = {k: _verdict(v) for k, v in detail.items()}
    if all(v == "sin datos" for v in verdicts.values()):
        return "gris", detail
    if "pierde" in verdicts.values():
        return "rojo", detail
    if "gana" in verdicts.values():
        return "verde", detail
    return "amarillo", detail


ADVICE = {
    "verde": "Ventaja demostrada. Apostar solo a cuota ≥ la mínima.",
    "amarillo": "No apostar: ventaja no demostrada.",
    "rojo": "No apostar: el mercado le gana al modelo (demostrado).",
    "gris": "No apostar: sin precio de mercado para medir la ventaja.",
}
