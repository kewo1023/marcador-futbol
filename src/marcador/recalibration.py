"""Capa de recalibracion: corrige la salida del modelo con forma reciente.

DE DONDE SALE
-------------
El diagnostico de la F4 encontro que el modelo pierde contra el mercado sobre
todo en victorias locales, y que la causa no es el nivel (da 43.6% de media
contra 43.9% del mercado) sino la DISCRIMINACION: correlacion con el resultado
0.3925 frente a 0.4325 del mercado. Separa peor los partidos.

QUE SE DESCARTO ANTES DE LLEGAR AQUI
------------------------------------
- Ventaja de local por equipo: la variacion entre equipos (6.71%) es
  compatible con el puro azar (6.06%). Seria ajustar ruido.
- Mezclar la fuerza estimada con tiros a puerta: no discrimina mejor
  (correlacion 0.3925 -> 0.3932) y destroza los empates, que caen del 23.0% al
  15.9% cuando el real es 22.5%. El bootstrap la descarta: -0.0008, p=0.52.

QUE HACE ESTA CAPA
------------------
Toma las tres probabilidades del modelo y las corrige con medias moviles de
forma reciente —tiros, tiros a puerta, corners y goles a favor y en contra—
mediante una regresion logistica multinomial. Las features son las mismas que
el modelo Poisson NO puede ver: el motor solo cuenta goles, y un equipo que
genera mucho y no marca es indistinguible para el de uno que no genera.

TODA FEATURE SE CALCULA CON PARTIDOS ANTERIORES AL KICKOFF. La ventana rueda y
nunca incluye el partido que se esta prediciendo.
"""
from collections import defaultdict, deque

import numpy as np
from scipy.optimize import minimize

OUTCOMES = ("H", "D", "A")
EPS = 1e-12

FEATURES = ["sot_dif_h", "sot_dif_a", "sh_dif_h", "sh_dif_a",
            "cor_dif_h", "cor_dif_a", "gol_dif_h", "gol_dif_a"]


def rolling_features(rows, window=10):
    """Medias moviles por equipo con los ultimos `window` partidos ANTERIORES.

    Devuelve {match_id: {feature: valor}}. Un equipo sin historia recibe ceros,
    que en las features (todas diferencias) significa "promedio de la liga".
    """
    hist = defaultdict(lambda: deque(maxlen=window))
    out = {}
    for r in rows:
        h, a = r["home_team"], r["away_team"]

        def avg(team, key):
            # Se ignoran los huecos en vez de propagarlos. Son 2 partidos en
            # 19.909, pero un solo NULL tumbaba el pipeline entero: una feature
            # de forma tiene que degradarse, no romperse.
            v = [x[key] for x in hist[team] if x[key] is not None]
            return float(np.mean(v)) if v else 0.0

        out[r["match_id"]] = {
            "sot_dif_h": avg(h, "sot_f") - avg(h, "sot_a"),
            "sot_dif_a": avg(a, "sot_f") - avg(a, "sot_a"),
            "sh_dif_h": avg(h, "sh_f") - avg(h, "sh_a"),
            "sh_dif_a": avg(a, "sh_f") - avg(a, "sh_a"),
            "cor_dif_h": avg(h, "c_f") - avg(h, "c_a"),
            "cor_dif_a": avg(a, "c_f") - avg(a, "c_a"),
            "gol_dif_h": avg(h, "g_f") - avg(h, "g_a"),
            "gol_dif_a": avg(a, "g_f") - avg(a, "g_a"),
        }
        # El partido entra al historial DESPUES de generar sus features.
        # Si el partido no trae datos de eventos, entra con None y el promedio
        # lo salta; no se descarta el partido, porque su resultado si es valido.
        hist[h].append({"sot_f": r["hst"], "sot_a": r["ast"], "sh_f": r["hs"],
                        "sh_a": r["as"], "c_f": r["hc"], "c_a": r["ac"],
                        "g_f": r["fthg"], "g_a": r["ftag"]})
        hist[a].append({"sot_f": r["ast"], "sot_a": r["hst"], "sh_f": r["as"],
                        "sh_a": r["hs"], "c_f": r["ac"], "c_a": r["hc"],
                        "g_f": r["ftag"], "g_a": r["fthg"]})
    return out


def design_matrix(match_ids, model_probs, feats, mean=None, std=None):
    """Filas = partidos. Columnas = las 8 features estandarizadas.

    Las log-probabilidades del modelo NO van como columna: entran como offset,
    que es lo que mantiene a esta capa siendo una correccion y no un modelo
    nuevo que compite con el motor.
    """
    X = np.array([[feats[i][f] for f in FEATURES] for i in match_ids], float)
    if mean is None:
        mean, std = X.mean(0), X.std(0)
        std[std < 1e-9] = 1.0
    X = (X - mean) / std
    offset = np.array([[np.log(max(model_probs[i][k], EPS)) for k in OUTCOMES]
                       for i in match_ids])
    return X, offset, mean, std


def fit(X, offset, y, lam):
    """Logistica multinomial sobre el offset del modelo, SIN interceptos.

    score_k = log(p_modelo_k) + X . w_k

    Partir del log del modelo significa que con todos los pesos en cero la capa
    devuelve exactamente las probabilidades del modelo. La regularizacion, por
    tanto, no encoge hacia "nada": encoge hacia NO TOCAR NADA, que es el
    comportamiento seguro por defecto.

    POR QUE NO HAY INTERCEPTOS, QUE FUE UNA CORRECCION
    -------------------------------------------------
    La primera version los tenia, y con ellos la capa mejoraba mucho las
    victorias locales (-0.0368, concluyente) mientras empeoraba empates
    (+0.0129) y visitantes (+0.0301), tambien de forma concluyente. O sea que
    movia masa hacia los locales en vez de separar mejor los partidos: subia la
    probabilidad media de local al 44.6% cuando la real del periodo era 41.6%.

    Sin interceptos la capa NO puede mover el nivel global —la media se queda
    en 43.4%, la del modelo— y solo puede reordenar partidos segun sus
    features. La ganancia de discriminacion SOBREVIVE a esa restriccion
    (correlacion con victoria local 0.3377 -> 0.3502) y el total incluso mejora
    un poco. Esa es la prueba de que lo que aporta es informacion y no un
    desplazamiento: si fuera desplazamiento, quitarle la palanca lo habria
    borrado.
    """
    n, p = X.shape
    k = len(OUTCOMES)

    def nll(b):
        W = b.reshape(p, k)
        z = offset + X @ W
        z = z - z.max(axis=1, keepdims=True)
        ls = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
        return -ls[np.arange(n), y].sum() + 0.5 * lam * np.sum(W ** 2)

    res = minimize(nll, np.zeros(p * k), method="L-BFGS-B",
                   options={"maxiter": 2000})
    return res.x


def predict(b, X, offset):
    W = b.reshape(X.shape[1], len(OUTCOMES))
    z = offset + X @ W
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)
