"""Los modelos tontos contra los que se mide todo lo demás.

Son deliberadamente simples. El punto de la fase 1 no es predecir bien: es
probar que el marcador funciona. Si el sistema de medición sirve con un modelo
tonto, sirve con cualquiera.

Dos baselines aquí, y el tercero (la cuota de cierre del mercado) sale de los
datos, no de un modelo.
"""
import datetime as dt
import json

MARKET_1X2 = "1X2"
OUTCOMES = ("H", "D", "A")


def register_model(con, model_version, family, params=None, notes=None):
    con.execute(
        """INSERT INTO model_versions (model_version, family, params_json,
                                       notes, created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(model_version) DO UPDATE SET
             params_json=excluded.params_json, notes=excluded.notes""",
        (model_version, family, json.dumps(params or {}), notes,
         dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
    con.commit()


# --- Baseline 1: frecuencia base --------------------------------------------

def base_rate(rows) -> dict:
    """'45% local, 27% empate, 28% visitante' para TODOS los partidos.

    En Excel sería una sola tabla dinámica: contar resultados y dividir por el
    total. No mira quién juega. Si un modelo no le gana a esto, no modela nada.
    """
    counts = {o: 0 for o in OUTCOMES}
    for r in rows:
        if r["ftr"] in counts:
            counts[r["ftr"]] += 1
    n = sum(counts.values())
    return {o: counts[o] / n for o in OUTCOMES}


# --- Baseline 2: Elo ---------------------------------------------------------

class Elo:
    """Un rating por equipo que sube y baja con cada resultado.

    Sorprendentemente difícil de superar, y por eso es la vara real: ganarle a
    la frecuencia base es trivial, ganarle a Elo no.

    Cómo funciona, sin matemáticas: cada equipo tiene un puntaje. Antes del
    partido se compara el puntaje del local (más una ventaja fija por jugar en
    casa) contra el del visitante, y de esa diferencia sale una expectativa. Si
    el resultado se aparta de lo esperado, los puntajes se mueven; si confirma
    lo esperado, se mueven poco. Es exactamente la lógica del ranking de
    ajedrez, aplicada a equipos.

    El empate se maneja como "medio punto para cada uno", igual que en ajedrez.
    """

    def __init__(self, k=20.0, home_adv=60.0, start=1500.0, draw_share=0.26):
        self.k = k                     # cuánto se mueve el rating por partido
        self.home_adv = home_adv       # ventaja de local, en puntos de Elo
        self.start = start
        self.draw_share = draw_share   # porción fija reservada al empate
        self.ratings = {}

    def rating(self, team):
        return self.ratings.get(team, self.start)

    def expected_home(self, home, away):
        """Probabilidad esperada del local en la escala de dos resultados."""
        diff = self.rating(home) + self.home_adv - self.rating(away)
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))

    def predict(self, home, away) -> dict:
        """Convierte la expectativa de dos vías en probabilidades de 1X2.

        Elo nativo no sabe de empates. El apaño estándar: se reserva una
        porción fija para el empate y el resto se reparte proporcionalmente.
        Es tosco a propósito — es un baseline, no el modelo.
        """
        e = self.expected_home(home, away)
        rest = 1.0 - self.draw_share
        return {"H": e * rest, "D": self.draw_share, "A": (1 - e) * rest}

    def update(self, home, away, ftr):
        """Ajusta los dos ratings después de ver el resultado."""
        e = self.expected_home(home, away)
        score = {"H": 1.0, "D": 0.5, "A": 0.0}[ftr]
        delta = self.k * (score - e)
        self.ratings[home] = self.rating(home) + delta
        self.ratings[away] = self.rating(away) - delta


# --- Baseline 3: el mercado --------------------------------------------------

def _has(row, col):
    try:
        return row[col] is not None
    except (KeyError, IndexError):
        return False


def market_probs(row) -> dict | None:
    """Cuota de cierre del mercado, convertida a probabilidad y sin margen.

    Una cuota de 2.00 significa "paga el doble", o sea 1/2.00 = 50%. Pero las
    tres probabilidades implícitas de un partido suman MÁS de 1 (típicamente
    1.02-1.05): ese exceso es el margen de la casa. Dividir cada una por la
    suma lo quita y deja probabilidades que sí suman 1.

    Es el techo del proyecto: representa toda la información pública más el
    dinero de los profesionales. Acercarse ya es un resultado.

    QUÉ COLUMNA SE USA, Y POR QUÉ CAMBIÓ. Se prefiere el promedio de todas las
    casas (AvgC*) y se cae a Pinnacle (PSC*) si no está.

    Al principio del proyecto la referencia era Pinnacle sola. La fuente dejó
    de publicarla el 17/01/2026: falta en 170 partidos de 2025/26 y en toda la
    temporada 2026/27. Seguir con ella habría dejado al track record en vivo
    sin techo contra el cual medirse — justo la parte que la F3 automatizó.

    El cambio además mejora la referencia: el promedio de varias casas es el
    consenso del mercado, no la opinión de una. El costo es que las cifras
    calculadas contra Pinnacle y contra el promedio no son directamente
    comparables, y por eso el baseline viejo (market-close-v1) se conserva sin
    tocar y el nuevo se registra aparte.
    """
    h = row["avgch"] if _has(row, "avgch") else row["psch"]
    d = row["avgcd"] if _has(row, "avgcd") else row["pscd"]
    a = row["avgca"] if _has(row, "avgca") else row["psca"]
    if not h or not d or not a or min(h, d, a) <= 1.0:
        return None
    ph, pd_, pa = 1 / h, 1 / d, 1 / a
    total = ph + pd_ + pa
    return {"H": ph / total, "D": pd_ / total, "A": pa / total}
