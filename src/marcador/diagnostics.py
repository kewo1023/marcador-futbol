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
from .scoring import bootstrap_diff

EPS = 1e-15

# Con menos de esto el numero de un grupo es humo. `analyse` lo lleva escrito
# en su cuerpo desde la F4; aqui se nombra para poder reutilizarlo.
MIN_GROUP = 15


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
                    "league": league,
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


def _newcomers_by_league(matches):
    """Los ascendidos, calculados DENTRO de cada liga.

    Con una sola liga daba igual y `newcomers_by_season` bastaba. Al juntar
    cinco deja de bastar: "equipo que no jugo la temporada anterior" solo
    significa algo dentro de su propia competicion. Sobre el conjunto mezclado,
    el primer partido de cualquier liga contra otra volveria ascendida a media
    Europa.
    """
    out = {}
    for lg in sorted({m.get("league") for m in matches}):
        sub = [m for m in matches if m.get("league") == lg]
        for season, teams in newcomers_by_season(sub).items():
            out.setdefault(season, set()).update(teams)
    return out


def analyse_paired(matches, model_probs, seasons=None, extra_segments=None,
                   min_group=MIN_GROUP, seed=0):
    """Igual que `analyse`, pero dice ademas si la brecha se distingue del ruido.

    `analyse` compara promedios, y con una sola liga era lo unico que se podia
    hacer: partido el bloque en segmentos, los grupos quedaban en 100 o 200
    partidos — suficiente para calcular una media, no para creersela. Con cinco
    ligas los grupos crecen lo bastante para meterles el mismo bootstrap
    pareado que usa el gate de la F4 (regla 6), modelo contra mercado y sobre
    los MISMOS partidos.

    Por que importa aqui y no solo en el gate: este modulo genera las hipotesis
    que despues cuestan sesiones enteras de perseguir. Un grupo puede encabezar
    la tabla por promedio y no sobrevivir al intervalo; sin esta marca, ese es
    justo el que uno sale a atacar primero.

    `extra_segments` son cortes adicionales como (nombre, funcion) — el de liga,
    por ejemplo, que con una sola competicion no existia.

    Devuelve las mismas claves que `analyse` mas ci_low, ci_high, p_value y
    concluyente.
    """
    sel = [m for m in matches
           if m["id"] in model_probs and m["market"]
           and (seasons is None or m["season"] in seasons)]
    if not sel:
        return [], 0
    newcomers = _newcomers_by_league(matches)

    def loss(p, ftr):
        return -math.log(max(p.get(ftr, 0.0), EPS))

    cortes = [(name, fn) for name, fn, _ in segments(sel, model_probs, newcomers)]
    cortes += list(extra_segments or [])

    rows = []
    for name, key_fn in cortes:
        groups = {}
        for m in sel:
            k = key_fn(m)
            if k is None:
                continue
            modelo, mercado = groups.setdefault(k, ([], []))
            modelo.append(loss(model_probs[m["id"]]["probs"], m["ftr"]))
            mercado.append(loss(m["market"], m["ftr"]))
        for k, (modelo, mercado) in sorted(groups.items()):
            n = len(modelo)
            if n < min_group:
                continue
            # 'a' es el modelo y 'b' el mercado, asi que un diff positivo es el
            # modelo perdiendo: la misma orientacion que 'brecha' en `analyse`.
            diff, lo, hi, p, _ = bootstrap_diff(modelo, mercado, seed=seed)
            rows.append({"segmento": name, "grupo": str(k), "n": n,
                         "modelo": sum(modelo) / n, "mercado": sum(mercado) / n,
                         "brecha": diff, "peso": diff * n / len(sel),
                         "ci_low": lo, "ci_high": hi, "p_value": p,
                         # el intervalo no contiene cero
                         "concluyente": (lo > 0) == (hi > 0)})
    return rows, len(sel)
