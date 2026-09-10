"""Nombres de equipo: de cada fuente al vocabulario canonico de la base.

POR QUE ESTA TABLA NO ES OPCIONAL
---------------------------------
El match_id se construye con la fecha y los nombres de los dos equipos
(`ingest.make_match_id`). El resultado de un partido llega desde
football-data.co.uk con SUS nombres —'Sevilla', 'Ath Bilbao', 'Man United'—
y cae sobre la fila que tenga ese id. Si el fixture se escribio con otro
nombre, 'Sevilla FC', el id es otro, la prediccion nunca se conecta con el
resultado, y por la regla 3 tampoco se puede corregir: queda huerfana para
siempre y como un agujero en el track record.

Por eso el canonico es el de football-data.co.uk, que es quien trae los
resultados, y cualquier otra fuente se traduce a el ANTES de crear el id.

POR QUE UN NOMBRE DESCONOCIDO ABORTA EL PARTIDO
-----------------------------------------------
Adivinar ('Spurs' se parece a... ¿Sunderland?) produce exactamente el agujero
de arriba, y silencioso. Un partido saltado con aviso lo atrapa 05_score.py
cuando se juegue sin prediccion; uno predicho con el nombre equivocado no lo
atrapa nadie.

La tabla se genero emparejando por similitud y revisando a mano los nueve
casos donde la similitud fallo. Cuando una liga cambie de equipos (ascensos),
la falla va a ser ruidosa: el nombre nuevo no esta aqui y el partido se
salta con aviso. Ese es el comportamiento deseado.
"""


class UnknownTeam(KeyError):
    """Un nombre que ninguna tabla reconoce. Se captura por partido, no por
    corrida: un ascendido sin alias no puede parar la prediccion de las otras
    cuatro ligas."""


# fixturedownload.com -> football-data.co.uk, por liga.
# Los que coinciden exactamente tambien van, a proposito: la tabla es la lista
# completa de lo que se acepta, no solo de lo que cambia.
FIXTUREDOWNLOAD = {
    "E0": {
        "Arsenal": "Arsenal",
        "Aston Villa": "Aston Villa",
        "Bournemouth": "Bournemouth",
        "Brentford": "Brentford",
        "Brighton": "Brighton",
        "Chelsea": "Chelsea",
        "Coventry": "Coventry",
        "Crystal Palace": "Crystal Palace",
        "Everton": "Everton",
        "Fulham": "Fulham",
        "Hull": "Hull",
        "Ipswich": "Ipswich",
        "Leeds": "Leeds",
        "Liverpool": "Liverpool",
        "Man City": "Man City",
        "Man Utd": "Man United",
        "Newcastle": "Newcastle",
        "Nott'm Forest": "Nott'm Forest",
        "Spurs": "Tottenham",
        "Sunderland": "Sunderland",
    },
    "SP1": {
        "Athletic Club": "Ath Bilbao",
        "Atlético de Madrid": "Ath Madrid",
        "CA Osasuna": "Osasuna",
        "Celta": "Celta",
        "Deportivo Alavés": "Alaves",
        "Elche CF": "Elche",
        "FC Barcelona": "Barcelona",
        "Getafe CF": "Getafe",
        "Levante UD": "Levante",
        "Málaga CF": "Malaga",
        "R. Racing Club": "Santander",
        "RC Deportivo": "La Coruna",
        "RCD Espanyol de Barcelona": "Espanol",
        "Rayo Vallecano": "Vallecano",
        "Real Betis": "Betis",
        "Real Madrid": "Real Madrid",
        "Real Sociedad": "Sociedad",
        "Sevilla FC": "Sevilla",
        "Valencia CF": "Valencia",
        "Villarreal CF": "Villarreal",
    },
    "D1": {
        "1. FC Köln": "FC Koln",
        "1. FC Union Berlin": "Union Berlin",
        "1. FSV Mainz 05": "Mainz",
        "Bayer 04 Leverkusen": "Leverkusen",
        "Borussia Dortmund": "Dortmund",
        "Borussia Mönchengladbach": "M'gladbach",
        "Eintracht Frankfurt": "Ein Frankfurt",
        "FC Augsburg": "Augsburg",
        "FC Bayern München": "Bayern Munich",
        "FC Schalke 04": "Schalke 04",
        "Hamburger SV": "Hamburg",
        "RB Leipzig": "RB Leipzig",
        "SC Paderborn 07": "Paderborn",
        "SV Elversberg": "Elversberg",
        "SV Werder Bremen": "Werder Bremen",
        "Sport-Club Freiburg": "Freiburg",
        "TSG Hoffenheim": "Hoffenheim",
        "VfB Stuttgart": "Stuttgart",
    },
    "I1": {
        "Atalanta": "Atalanta",
        "Bologna": "Bologna",
        "Cagliari": "Cagliari",
        "Como": "Como",
        "Fiorentina": "Fiorentina",
        "Frosinone": "Frosinone",
        "Genoa": "Genoa",
        "Internazionale": "Inter",
        "Juventus": "Juventus",
        "Lazio": "Lazio",
        "Lecce": "Lecce",
        "Milan": "Milan",
        "Monza": "Monza",
        "Napoli": "Napoli",
        "Parma": "Parma",
        "Roma": "Roma",
        "Sassuolo": "Sassuolo",
        "Torino": "Torino",
        "Udinese": "Udinese",
        "Venezia": "Venezia",
    },
    "F1": {
        "AJ Auxerre": "Auxerre",
        "AS Monaco": "Monaco",
        "Angers SCO": "Angers",
        "Estac Troyes": "Troyes",
        "FC Lorient": "Lorient",
        "Havre Athletic Club": "Le Havre",
        "LOSC Lille": "Lille",
        "Le Mans FC": "Le Mans",
        "OGC Nice": "Nice",
        "Olympique Lyonnais": "Lyon",
        "Olympique de Marseille": "Marseille",
        "Paris FC": "Paris FC",
        "Paris Saint-Germain": "Paris SG",
        "RC Lens": "Lens",
        "RC Strasbourg Alsace": "Strasbourg",
        "Stade Brestois 29": "Brest",
        "Stade Rennais FC": "Rennes",
        "Toulouse FC": "Toulouse",
    },
}


def canonical(table: dict, league: str, name: str) -> str:
    """El nombre canonico, o UnknownTeam. Nunca adivina."""
    name = (name or "").strip()
    try:
        return table[league][name]
    except KeyError:
        raise UnknownTeam(f"{league}: {name!r} no esta en la tabla de alias") from None
