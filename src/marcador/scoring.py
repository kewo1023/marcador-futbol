"""El marcador: las métricas con las que se juzga cualquier modelo.

Esta es la pieza que se construye ANTES que el modelo. Un modelo que "se
corrige solo" necesita saber en qué dirección corregirse, y eso solo lo da un
sistema de medición que ya existía.
"""
import datetime as dt
import math

OUTCOMES_1X2 = ("H", "D", "A")
EPS = 1e-15  # evita log(0), que es infinito


def log_loss(pred_probs, actual) -> float:
    """Castiga fuerte la confianza equivocada.

    Es -log(probabilidad que le diste al resultado que de verdad pasó). Si
    dijiste 0.70 y pasó, sumas 0.36. Si dijiste 0.02 y pasó, sumas 3.9. Esa
    asimetría es el punto: un modelo que casi nunca se equivoca pero cuando se
    equivoca estaba segurísimo es un modelo peligroso, y log-loss lo detecta
    donde accuracy no.

    Es la métrica que decide si un modelo reemplaza a otro.
    """
    total = 0.0
    for probs, act in zip(pred_probs, actual):
        p = min(max(probs.get(act, 0.0), EPS), 1.0)
        total += -math.log(p)
    return total / len(actual)


def brier_score(pred_probs, actual, outcomes=OUTCOMES_1X2) -> float:
    """Error cuadrático de la probabilidad, sumado sobre los tres resultados.

    Más estable que log-loss cuando hay pocos partidos, porque no explota
    cuando una probabilidad se acerca a cero. Se reporta junto a log-loss como
    segunda opinión, no como criterio de decisión.
    """
    total = 0.0
    for probs, act in zip(pred_probs, actual):
        for o in outcomes:
            y = 1.0 if o == act else 0.0
            total += (probs.get(o, 0.0) - y) ** 2
    return total / len(actual)


def accuracy(pred_probs, actual) -> float:
    """Solo como dato de contexto. Nunca para decidir nada (regla 5).

    Está aquí porque es lo primero que pregunta cualquiera que vea el
    dashboard, y es mejor mostrarlo con la advertencia al lado que dejar el
    hueco para que se lo imaginen.
    """
    hits = sum(1 for probs, act in zip(pred_probs, actual)
               if max(probs, key=probs.get) == act)
    return hits / len(actual)


def calibration_bins(pred_probs, actual, outcomes=OUTCOMES_1X2, n_bins=10):
    """La curva de calibración: ¿cuando dices 70%, pasa 7 de cada 10 veces?

    Se agrupa CADA probabilidad emitida (no cada partido) en buckets de 10%, y
    dentro de cada bucket se compara el promedio prometido contra la frecuencia
    real observada. Un modelo honesto cae sobre la diagonal.

    Es el gráfico que revela lo que ninguna métrica de un solo número muestra:
    si el modelo es exagerado (dice 80% y pasa 65%) o tímido (dice 55% y pasa
    70%). Un modelo tímido se arregla; uno exagerado es más grave, porque su
    error crece justo donde uno más confiaría en él.
    """
    bins = [{"low": i / n_bins, "high": (i + 1) / n_bins,
             "n": 0, "sum_pred": 0.0, "hits": 0} for i in range(n_bins)]
    for probs, act in zip(pred_probs, actual):
        for o in outcomes:
            p = probs.get(o)
            if p is None:
                continue
            # min() mete el 1.0 exacto en el último bucket en vez de crear uno.
            idx = min(int(p * n_bins), n_bins - 1)
            b = bins[idx]
            b["n"] += 1
            b["sum_pred"] += p
            b["hits"] += 1 if o == act else 0
    for b in bins:
        b["mean_pred"] = b["sum_pred"] / b["n"] if b["n"] else None
        b["observed_rate"] = b["hits"] / b["n"] if b["n"] else None
    return bins


def evaluate(pred_probs, actual, outcomes=OUTCOMES_1X2) -> dict:
    """Las tres métricas de una vez, sobre el mismo conjunto."""
    return {
        "n_matches": len(actual),
        "log_loss": log_loss(pred_probs, actual),
        "brier": brier_score(pred_probs, actual, outcomes),
        "accuracy": accuracy(pred_probs, actual),
    }


# --- Persistencia -----------------------------------------------------------

def save_metrics(con, model_version, market, eval_set, results):
    con.execute(
        """INSERT INTO metrics (model_version, market, eval_set, n_matches,
                                log_loss, brier, accuracy, computed_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(model_version, market, eval_set) DO UPDATE SET
             n_matches=excluded.n_matches, log_loss=excluded.log_loss,
             brier=excluded.brier, accuracy=excluded.accuracy,
             computed_at=excluded.computed_at""",
        (model_version, market, eval_set, results["n_matches"],
         results["log_loss"], results["brier"], results["accuracy"],
         dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
    con.commit()


def save_calibration(con, model_version, market, eval_set, bins):
    for b in bins:
        con.execute(
            """INSERT INTO calibration_bins (model_version, market, eval_set,
                   bin_low, bin_high, n, mean_pred, observed_rate)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(model_version, market, eval_set, bin_low)
               DO UPDATE SET n=excluded.n, mean_pred=excluded.mean_pred,
                             observed_rate=excluded.observed_rate""",
            (model_version, market, eval_set, b["low"], b["high"],
             b["n"], b["mean_pred"], b["observed_rate"]))
    con.commit()


def score_from_db(con, model_version, market, seasons=None, outcomes=OUTCOMES_1X2):
    """Mide un modelo leyendo lo que quedo REGISTRADO, no lo que el script creyo.

    `seasons` restringe la evaluacion a un conjunto de temporadas. Sirve para
    separar el bloque donde se eligen los hiperparametros del bloque donde se
    reporta el resultado: elegir xi mirando las mismas temporadas que luego se
    reportan es una forma sutil de leakage, y produce un numero que no se
    sostiene en vivo.

    Devuelve (metricas, predicciones, resultados) para poder reutilizar las dos
    ultimas en la curva de calibracion sin volver a consultar.
    """
    sql = """SELECT p.match_id, p.outcome, p.prob, m.ftr
             FROM predictions p JOIN matches m ON m.match_id = p.match_id
             WHERE p.model_version = ? AND p.market = ? AND m.ftr IS NOT NULL"""
    args = [model_version, market]
    if seasons:
        sql += f" AND m.season IN ({','.join('?' * len(seasons))})"
        args += list(seasons)

    by_match = {}
    for r in con.execute(sql, args):
        slot = by_match.setdefault(r["match_id"], {"probs": {}, "ftr": r["ftr"]})
        slot["probs"][r["outcome"]] = r["prob"]

    preds, actual = [], []
    for slot in by_match.values():
        # Un partido con menos de tres probabilidades esta incompleto y se
        # descarta entero: puntuarlo a medias inventaria una comparacion.
        if len(slot["probs"]) != len(outcomes):
            continue
        preds.append(slot["probs"])
        actual.append(slot["ftr"])

    if not actual:
        return None, [], []
    return evaluate(preds, actual, outcomes), preds, actual


def paired_bootstrap(con, model_a, model_b, market="1X2", seasons=None,
                     n_boot=20000, seed=0):
    """Compara dos modelos sobre los MISMOS partidos y dice si la diferencia
    se distingue del ruido.

    Por que hace falta. Dos modelos pueden separarse por 0.002 de log-loss y
    que eso no signifique nada: con 1730 partidos, esa diferencia cabe holgada
    dentro de la variacion que produce el azar de que temporada tocó. Declarar
    ganador sin medir eso es la forma mas facil de promover un modelo peor —
    y es exactamente lo que el gate de la F4 tiene que impedir.

    El remuestreo es PAREADO: se remuestrean partidos, no modelos, y cada
    partido se lleva las dos predicciones juntas. Eso conserva el
    emparejamiento y es lo que da potencia cuando los dos modelos aciertan y
    fallan en los mismos partidos difíciles, que es justo lo que pasa aqui.

    Devuelve (diferencia_media, lo, hi, p). Negativo = model_a es mejor.
    Si el intervalo [lo, hi] contiene 0, la diferencia no es concluyente.
    """
    import numpy as np

    sql = """SELECT p.match_id, p.prob FROM predictions p
             JOIN matches m ON m.match_id = p.match_id
             WHERE p.model_version = ? AND p.market = ? AND p.outcome = m.ftr
               AND m.ftr IS NOT NULL"""
    args_tail = []
    if seasons:
        sql += f" AND m.season IN ({','.join('?' * len(seasons))})"
        args_tail = list(seasons)

    def hit_probs(mv):
        return {r["match_id"]: r["prob"]
                for r in con.execute(sql, [mv, market] + args_tail)}

    pa, pb = hit_probs(model_a), hit_probs(model_b)
    common = sorted(set(pa) & set(pb))
    if len(common) < 30:
        return None

    la = np.array([-math.log(max(pa[k], EPS)) for k in common])
    lb = np.array([-math.log(max(pb[k], EPS)) for k in common])
    d = la - lb

    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(axis=1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return float(d.mean()), float(lo), float(hi), float(p), len(common)
