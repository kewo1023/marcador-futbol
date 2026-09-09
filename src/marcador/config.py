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
# Códigos de football-data.co.uk: E0 = Premier League, SP1 = LaLiga,
# D1 = Bundesliga, I1 = Serie A, F1 = Ligue 1.
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

# Partidos por jugar de los proximos dias, todas las ligas en un solo archivo.
# Solo trae una ventana corta: en parones de seleccion puede venir sin una liga
# entera, y eso es normal, no un error.
FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"

# Muchos servidores rechazan un user-agent de librería. Este es el mínimo que
# la fuente acepta.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


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

# Modelo que emite las predicciones en vivo. Se cambia solo cuando la F4
# promueva uno nuevo, y ese cambio queda en el historial de git.
PRODUCTION_MODEL = "dixon-coles-xi0020-reg002-v1"
PRODUCTION_XI = 0.002
PRODUCTION_REG = 0.002
PRODUCTION_USE_RHO = True


def season_label(season: str) -> str:
    """'2425' -> '2024/25'. Solo para mostrar, nunca para guardar."""
    return f"20{season[:2]}/{season[2:]}"
