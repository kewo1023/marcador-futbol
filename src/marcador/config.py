"""Configuración del proyecto. Un solo lugar donde cambiar el alcance."""
import os
from pathlib import Path

# Raíz del proyecto: dos niveles arriba de este archivo.
# Se calcula en vez de escribirse para que no haya una ruta absoluta en el repo.
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "marcador.sqlite"

# --- Alcance -----------------------------------------------------------------
# Una sola liga. Ampliar después es fácil; empezar ancho es como uno se atora.
# Códigos de football-data.co.uk.
#
# POR QUE CINCO Y NO UNA. El proyecto arrancó con la Premier sola, y fue la
# decisión correcta para empezar: ampliar después es fácil, empezar ancho es
# como uno se atora. Dejó de serlo cuando el gate de la F4 rechazó una mejora
# real (-0.0026 de log-loss) por falta de potencia: con 790 partidos solo puede
# declarar concluyentes diferencias de 0.0060 o mayores, y validar aquella
# habría exigido once temporadas de una liga.
#
# Cinco ligas dan ~1750 partidos por temporada en vez de 380. El bloque del
# gate pasa de 790 a ~5000, que es justo el umbral que hacía falta.
LEAGUES = {
    "E0": "Premier League",
    "SP1": "LaLiga",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "F1": "Ligue 1",
}

# Liga por defecto para lo que todavía mira una sola (el árbitro, por ejemplo,
# solo existe en E0).
LEAGUE = "E0"

# Temporadas en el formato de la fuente: "2425" = temporada 2024/25.
SEASONS = ["1516", "1617", "1718", "1819", "1920", "2021",
           "2122", "2223", "2324", "2425", "2526", "2627"]

# La temporada en curso. Es la unica que se re-baja en cada corrida del loop:
# las cerradas ya no cambian.
CURRENT_SEASON = SEASONS[-1]

# --- Fuente ------------------------------------------------------------------
# OJO: el subdominio www.football-data.co.uk responde 503 a peticiones
# programáticas. El dominio pelado sí responde. Verificado al construir F1.
BASE_URL = "https://football-data.co.uk/mmz4281"

# --- Proximos partidos ---------------------------------------------------------
# Desde el 2026-09-10 vienen de fixturedownload.com, un archivo por liga con la
# temporada COMPLETA. Football-data.co.uk sigue siendo la fuente del historico,
# de los resultados y de las cuotas de cierre — eso no cambia, y es lo que
# obliga a traducir los nombres de equipo (ver aliases.py).
#
# POR QUE SE CAMBIO. El archivo de fixtures de football-data.co.uk es una foto
# de ~3 dias que la fuente regenera cuando quiere. El 2026-09-10 llevaba 49 h
# congelada, cubria hasta el 10, y la jornada de las cinco ligas arrancaba el
# 11. Ninguna frecuencia de job arregla eso: el horizonte lo fija la fuente.
#
# LO QUE NO SE PUDO VERIFICAR. fixturedownload.com no publica terminos de uso
# (solo tiene /privacy) ni dice de donde saca los datos. Se usa como puente,
# detras de una capa de proveedor (fixtures.py) para que cambiar a una API con
# terminos explicitos sea reemplazar una funcion.
FIXTURES_BASE_URL = "https://fixturedownload.com/download"

# Codigo de liga nuestro -> nombre del archivo en la fuente de fixtures.
FIXTURE_SOURCES = {
    "E0": "epl",
    "SP1": "la-liga",
    "D1": "bundesliga",
    "I1": "serie-a",
    "F1": "ligue-1",
}

# Cuantos dias hacia adelante se PREDICE, y sobre cuantos se reporta salud.
#
# Con la fuente anterior no hacia falta: mostraba tres dias y ese era el tope.
# Con la temporada completa a la vista, sin tope se predeciria un partido de
# mayo con el modelo de septiembre — y como una prediccion escrita no se
# reemplaza (regla 3), esa seria la que contaria. Cada partido se predice lo
# mas cerca posible del kickoff, no lo mas pronto posible. Tres dias, con el
# job cada cuatro horas, da unas 18 oportunidades de emitir antes del partido
# y mantiene la frescura comparable a la del backtest (reajuste semanal).
#
# Y sobre la hora: la fuente pone 00:00 cuando la liga aun no la confirmo.
# Medido el 2026-09-10: 309 de 380 partidos de LaLiga la tenian sin confirmar,
# pero los de los dias siguientes la tenian toda. La senal de salud ya no es
# "cuando se escribio el archivo", es "los partidos que vienen, ¿tienen hora?".
FIXTURES_LOOKAHEAD_DAYS = 3

# --- Fuente ANTERIOR de fixtures (football-data.co.uk) ------------------------
# Ya no se usa en produccion. Se conserva la URL y las funciones de ingest.py
# que la leen para poder volver a medirla si hiciera falta.
#
# Partidos por jugar, todas las ligas en un solo archivo. Es el UNICO archivo
# de proximos partidos que publica la fuente: no hay version con mas horizonte.
#
# Es una FOTO, no una ventana que rueda con el dia. La fuente regenera el
# archivo cada cierto tiempo y cubre los dias siguientes al momento de
# escribirlo.
#
# Medido el 2026-09-10 a las 03:12 UTC: last-modified del martes 08/09 a las
# 18:07 UTC —33 horas antes— cubriendo del 08 al 10 de septiembre. Que una liga
# no aparezca significa que su jornada cae fuera de esa foto, no que no se
# juegue.
#
# Por eso el job de predecir corre dos veces al dia, para recoger la foto nueva
# poco despues de que se escriba. Y por eso 05_score.py comprueba despues de
# cada jornada si algun partido se jugo sin prediccion.
FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"

# Cuantas horas puede llevar el archivo sin regenerarse antes de considerarlo
# rancio.
#
# POR QUE HACE FALTA UN UMBRAL. Hasta el 2026-09-10, una corrida sin partidos
# imprimia "No hay partidos por jugar sin prediccion" y terminaba en verde, y
# ese mensaje era IDENTICO en los dos casos que hay que distinguir:
#
#   · no juega nadie en los proximos dias         -> correcto, nada que hacer
#   · la fuente lleva dias sin regenerar el archivo -> se estan perdiendo jornadas
#
# Medido ese dia: el archivo llevaba 34 horas con el mismo last-modified y
# cubria hasta el 10 de septiembre, con la jornada de las cinco ligas
# arrancando el 11. Tres corridas en verde, ninguna capaz de decirlo.
#
# 24 h porque la foto observada cubre unos tres dias: mientras se regenere a
# diario, ninguna jornada se cae. Pasado ese punto el margen empieza a comerse
# la ventana y hay que enterarse.
FIXTURES_STALE_HOURS = 24

# Muchos servidores rechazan un user-agent de librería. Este es el mínimo que
# la fuente acepta.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def league_label(code: str) -> str:
    return LEAGUES.get(code, code)


def season_url(season: str, league: str = LEAGUE) -> str:
    return f"{BASE_URL}/{season}/{league}.csv"


# --- Ledger ------------------------------------------------------------------
# Las predicciones NO pueden vivir solo en data/, que esta en .gitignore: el
# runner de GitHub Actions se destruye al terminar y se perderian. Se guardan
# en texto, versionadas, y eso ademas convierte al historial de git en la
# prueba de que la prediccion existia antes del partido — mas fuerte que una
# columna created_at que el propio sistema escribe.
#
# Solo van predicciones, resultados minimos y metricas: datos derivados. El
# volcado crudo de la fuente sigue fuera del repo (regla 2 de CLAUDE.md).
# El override por variable de entorno existe para poder correr el dashboard o
# los scripts contra otro ledger (una prueba, una copia) sin tocar el real.
LEDGER_DIR = Path(os.environ.get("MARCADOR_LEDGER_DIR", ROOT / "ledger"))
LEDGER_PREDICTIONS = LEDGER_DIR / "predictions.csv"
LEDGER_RESULTS = LEDGER_DIR / "results.csv"
LEDGER_METRICS = LEDGER_DIR / "metrics.csv"
LEDGER_MISSED = LEDGER_DIR / "missed.csv"
# La hora de cada partido va APARTE de las predicciones. Una prediccion es
# inmutable; la hora de un partido no (se aplazan, se mueven de dia). Mezclar
# las dos en un archivo obligaria a reescribir filas de prediccion para
# corregir un dato que no es de la prediccion.
LEDGER_FIXTURES = LEDGER_DIR / "fixtures.csv"

# Modelo que emite las predicciones en vivo. Se cambia solo cuando la F4
# promueva uno nuevo, y ese cambio queda en el historial de git.
PRODUCTION_MODEL = "dixon-coles-xi0020-reg002-v1"
PRODUCTION_XI = 0.002
PRODUCTION_REG = 0.002
PRODUCTION_USE_RHO = True


def season_label(season: str) -> str:
    """'2425' -> '2024/25'. Solo para mostrar, nunca para guardar."""
    return f"20{season[:2]}/{season[2:]}"
