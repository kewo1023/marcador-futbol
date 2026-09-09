"""Configuración del proyecto. Un solo lugar donde cambiar el alcance."""
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
           "2122", "2223", "2324", "2425", "2526"]

# --- Fuente ------------------------------------------------------------------
# OJO: el subdominio www.football-data.co.uk responde 503 a peticiones
# programáticas. El dominio pelado sí responde. Verificado al construir F1.
BASE_URL = "https://football-data.co.uk/mmz4281"

# Muchos servidores rechazan un user-agent de librería. Este es el mínimo que
# la fuente acepta.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def season_url(season: str, league: str = LEAGUE) -> str:
    return f"{BASE_URL}/{season}/{league}.csv"


def season_label(season: str) -> str:
    """'2425' -> '2024/25'. Solo para mostrar, nunca para guardar."""
    return f"20{season[:2]}/{season[2:]}"
