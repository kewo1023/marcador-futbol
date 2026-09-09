"""Los mercados que el motor puede predecir, y con que se mide cada uno.

LA PROMESA DE ESTA FASE, Y HASTA DONDE SE CUMPLE
------------------------------------------------
La idea era "el mismo motor apuntado a otra columna". Es cierta, con un matiz
que solo aparece al medirlo: Poisson exige varianza = media, y eso se cumple
en goles, amarillas y tiros a puerta, pero NO en corners ni en tiros totales.

La dispersion residual medida sobre 790 partidos, ya descontada la fuerza de
los equipos:

    goles            0.86    Poisson basta
    amarillas        0.86    Poisson basta
    tiros a puerta   0.99    Poisson basta
    corners          1.34    hace falta un parametro mas
    tiros totales    1.46    hace falta un parametro mas

En los dos ultimos la realidad se abre mas de lo que Poisson puede
representar. No hace falta otro modelo: la media la sigue estimando el mismo
motor y solo la distribucion predictiva pasa a binomial negativa, con la
dispersion estimada de los residuos. Un parametro, no un rediseno.

EL TECHO: DONDE HAY Y DONDE NO
------------------------------
La fuente publica cuotas de cierre para 1X2 y para over/under 2.5 goles, y
para nada mas. En corners, tarjetas y tiros solo se puede medir contra la
frecuencia base. Eso es una medicion mas debil y hay que tratarla como tal: se
sabe si el modelo aporta algo, no cuanto le falta para lo alcanzable.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    key: str            # identificador estable, va a la tabla predictions
    label: str
    home_col: str
    away_col: str
    lines: tuple        # lineas de over/under a evaluar
    use_rho: bool       # la correccion de marcadores bajos solo aplica a goles
    has_market_odds: bool


MARKETS = [
    Market("goles", "Goles", "fthg", "ftag", (1.5, 2.5, 3.5), True, True),
    Market("corners", "Corners", "hc", "ac", (8.5, 9.5, 10.5, 11.5), False, False),
    Market("tarjetas", "Tarjetas amarillas", "hy", "ay", (2.5, 3.5, 4.5), False, False),
    Market("tiros_puerta", "Tiros a puerta", "hst", "ast", (7.5, 8.5, 9.5), False, False),
]

BY_KEY = {m.key: m for m in MARKETS}


def market_code(market: Market, line: float) -> str:
    """Nombre del mercado tal como se guarda: 'CORNERS_OU105'."""
    return f"{market.key.upper()}_OU{str(line).replace('.', '')}"


def ou_market_probs(row, line):
    """Probabilidad implicita del mercado para over/under, sin margen.

    Solo existe para 2.5 goles. Devuelve None en todo lo demas, y quien llama
    tiene que tratar ese None como 'aqui no hay techo', no como un error.
    """
    if abs(line - 2.5) > 1e-9:
        return None
    try:
        o, u = row["avgc_o25"], row["avgc_u25"]
    except (KeyError, IndexError):
        return None
    if not o or not u or min(o, u) <= 1.0:
        return None
    po, pu = 1 / o, 1 / u
    total = po + pu
    return {"OVER": po / total, "UNDER": pu / total}
