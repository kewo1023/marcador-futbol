"""Donde falla el modelo. Genera hipotesis para la siguiente iteracion.

QUE ES Y QUE NO ES
------------------
Es un generador de hipotesis, no un criterio de decision. Ver que el modelo
pierde en cierto tipo de partido sugiere que mirar; no autoriza a cambiar nada
en base a eso. Cualquier cambio que salga de aqui tiene que pasar por el gate
igual que los demas, sobre datos que no incluyan el bloque donde se encontro
la pista. Si no, esto se convierte en afinar contra el conjunto de prueba de
forma manual, que es la misma trampa de siempre con otra ropa.

POR QUE SE COMPARA CONTRA EL MERCADO Y NO CONTRA UN NUMERO SUELTO
-----------------------------------------------------------------
Un log-loss de 1.03 en un segmento no dice nada por si solo: puede ser un
segmento intrinsecamente dificil. Lo que importa es cuanto se pierde CONTRA EL
MERCADO en ese segmento, porque el mercado enfrenta la misma dificultad. Un
segmento donde el modelo pierde poco contra el mercado esta bien resuelto
aunque su log-loss absoluto sea alto.
"""
import datetime as dt
import math

from .baseline import market_probs

EPS = 1e-15


def load_context(con, league):
    """Los partidos con los atributos que el diagnostico necesita segmentar."""
    rows = con.execute(
        """SELECT match_id, match_date, season, home_team, away_team,
                  fthg, ftag, ftr, hr, ar,
                  avgch, avgcd, avgca, psch, pscd, psca
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date""", (league,)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["match_id"], "season": r["season"],
                    "date": dt.date.fromisoformat(r["match_date"]),
                    "home": r["home_team"], "away": r["away_team"],
                    "ftr": r["ftr"], "reds": (r["hr"] or 0) + (r["ar"] or 0),
                    "market": market_probs(r)})
    return out


def newcomers_by_season(matches):
    """Equipos que no jugaron la temporada anterior: los recien ascendidos.

    Es el segmento que en la F2 resulto ser la causa de las probabilidades
    extremas, asi que vale la pena vigilarlo de forma permanente y no solo una
    vez.
    """
    by_season = {}
    for m in matches:
        by_season.setdefault(m["season"], set()).update([m["home"], m["away"]])
    seasons = sorted(by_season)
    out = {}
    for prev, cur in zip(seasons, seasons[1:]):
        out[cur] = by_season[cur] - by_season[prev]
    return out


def segments(matches, losses_by_id, newcomers):
    """Define los cortes. Cada uno devuelve (nombre, funcion de pertenencia)."""
    def month_bucket(m):
        # Agosto-octubre: los parametros vienen de la temporada anterior y los
        # ascendidos no tienen historia. Es donde cabe esperar mas error.
        return m["date"].month in (8, 9, 10)

    return [
        ("por temporada", lambda m: m["season"], None),
        ("por resultado", lambda m: {"H": "gana local", "D": "empate",
                                     "A": "gana visitante"}[m["ftr"]], None),
        ("con equipo recien ascendido",
         lambda m: ("si" if (m["home"] in newcomers.get(m["season"], set())
                             or m["away"] in newcomers.get(m["season"], set()))
                    else "no"), None),
        ("con tarjeta roja", lambda m: "si" if m["reds"] > 0 else "no", None),
        ("arranque de temporada (ago-oct)",
         lambda m: "si" if month_bucket(m) else "no", None),
        ("segun lo desigual del partido",
         lambda m: _mismatch_bucket(losses_by_id, m), None),
    ]


def _mismatch_bucket(probs_by_id, m):
    """Que tan desigual creia el modelo que era el partido."""
    p = probs_by_id.get(m["id"], {}).get("probs")
    if not p:
        return None
    top = max(p.values())
    if top >= 0.60:
        return "favorito claro (>60%)"
    if top >= 0.45:
        return "favorito moderado"
    return "parejo (<45%)"


def analyse(matches, model_probs, seasons=None):
    """Compara el modelo contra el mercado, segmento por segmento.

    `model_probs` es {match_id: {"probs": {...}}}.
    """
    sel = [m for m in matches
           if m["id"] in model_probs and m["market"]
           and (seasons is None or m["season"] in seasons)]
    newcomers = newcomers_by_season(matches)

    def loss(p, ftr):
        return -math.log(max(p.get(ftr, 0.0), EPS))

    rows = []
    for name, key_fn, _ in segments(sel, model_probs, newcomers):
        groups = {}
        for m in sel:
            k = key_fn(m)
            if k is None:
                continue
            g = groups.setdefault(k, {"n": 0, "model": 0.0, "market": 0.0})
            g["n"] += 1
            g["model"] += loss(model_probs[m["id"]]["probs"], m["ftr"])
            g["market"] += loss(m["market"], m["ftr"])
        for k, g in sorted(groups.items()):
            if g["n"] < 15:      # con menos de 15 partidos el numero es humo
                continue
            model = g["model"] / g["n"]
            market = g["market"] / g["n"]
            rows.append({"segmento": name, "grupo": str(k), "n": g["n"],
                         "modelo": model, "mercado": market,
                         "brecha": model - market,
                         # cuanto de la brecha TOTAL aporta este grupo
                         "peso": (model - market) * g["n"] / len(sel)})
    return rows, len(sel)
