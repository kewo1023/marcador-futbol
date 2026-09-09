"""Esquema de la base de datos y utilidades de conexión.

El esquema es el corazón del proyecto: las reglas 3 y 4 del CLAUDE.md
(predicción inmutable, cero información del futuro) están impuestas por la
base de datos con triggers, no por la disciplina de quien escribe el código.

La diferencia importa. Una regla escrita en un README se rompe sin que nadie
se entere. Un trigger aborta la escritura y el script se cae con un error.
"""
import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- matches: el hecho histórico. Una fila por partido jugado.
-- Se llena desde los CSV de la fuente. Es lo único que se re-ingesta.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    match_id      TEXT PRIMARY KEY,   -- 'E0_2024-08-16_Man United_Fulham'
    league        TEXT NOT NULL,
    season        TEXT NOT NULL,      -- '2425'
    match_date    TEXT NOT NULL,      -- ISO 'YYYY-MM-DD', ordenable como texto
    kickoff_utc   TEXT,               -- ISO completo si la fuente trae la hora
    home_team     TEXT NOT NULL,
    away_team     TEXT NOT NULL,

    -- Resultado
    fthg          INTEGER,            -- goles local
    ftag          INTEGER,            -- goles visitante
    ftr           TEXT CHECK (ftr IN ('H','D','A')),

    -- Mercados de la fase 5. Se ingestan desde ya aunque todavía no se usen:
    -- volver a bajar 11 temporadas después cuesta más que guardar 8 columnas.
    hc INTEGER, ac INTEGER,           -- corners
    hy INTEGER, ay INTEGER,           -- tarjetas amarillas
    hr INTEGER, ar INTEGER,           -- tarjetas rojas
    hs INTEGER, "as" INTEGER,         -- tiros ("as" va entre comillas: AS es
    hst INTEGER, ast INTEGER,         -- palabra reservada en SQL)
    referee TEXT,                     -- clave para el mercado de tarjetas

    -- Cuota de cierre de Pinnacle. Es el techo contra el que se mide el
    -- modelo: representa toda la información pública más el dinero profesional.
    psch REAL, pscd REAL, psca REAL,

    ingested_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_date   ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(league, season);

-- ---------------------------------------------------------------------------
-- model_versions: cada modelo que alguna vez emitió una predicción.
-- Sin esto no se puede responder "¿qué versión generó esta fila?", que es
-- la mitad de lo que hace auditable al sistema.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    model_version TEXT PRIMARY KEY,   -- 'baseline-v1', 'dixon-coles-v1'
    family        TEXT NOT NULL,      -- 'baseline', 'dixon-coles'
    params_json   TEXT,               -- hiperparámetros, como texto JSON
    notes         TEXT,
    created_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- predictions: SOLO LECTURA una vez escrita. Aquí vive la regla 3.
--
-- Una fila por (partido, modelo, mercado, resultado posible). Un partido de
-- 1X2 son tres filas que suman 1.0. Guardarlo así en vez de tres columnas
-- hace que la misma tabla sirva para over/under, corners y tarjetas en la
-- fase 5 sin migrar nada.
--
-- info_cutoff es la columna que impone la regla 4: la fecha más reciente que
-- el modelo tenía permitido ver al generar esta predicción. Si es posterior
-- al partido, hubo data leakage, y el trigger lo rechaza.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id      TEXT NOT NULL REFERENCES matches(match_id),
    model_version TEXT NOT NULL REFERENCES model_versions(model_version),
    market        TEXT NOT NULL,      -- '1X2', 'OU25', 'CORNERS_OU95'
    outcome       TEXT NOT NULL,      -- 'H','D','A' | 'OVER','UNDER'
    prob          REAL NOT NULL CHECK (prob >= 0.0 AND prob <= 1.0),

    -- 'backtest' = generada hacia atrás para medir. 'live' = generada antes
    -- de un partido real que todavía no se jugaba.
    mode          TEXT NOT NULL CHECK (mode IN ('backtest','live')),

    info_cutoff   TEXT NOT NULL,      -- ISO 'YYYY-MM-DD'
    created_at    TEXT NOT NULL,

    UNIQUE (match_id, model_version, market, outcome)
);

CREATE INDEX IF NOT EXISTS idx_pred_model ON predictions(model_version, market);

-- Regla 4, impuesta por la base de datos: el corte de información tiene que
-- ser ANTERIOR al partido. Vale para backtest y para live por igual.
CREATE TRIGGER IF NOT EXISTS trg_pred_no_leakage
BEFORE INSERT ON predictions
FOR EACH ROW
WHEN NEW.info_cutoff >= (SELECT match_date FROM matches WHERE match_id = NEW.match_id)
BEGIN
    SELECT RAISE(ABORT,
      'DATA LEAKAGE: info_cutoff es igual o posterior a la fecha del partido');
END;

-- Regla 3, impuesta por la base de datos: escrita una vez, nunca se toca.
CREATE TRIGGER IF NOT EXISTS trg_pred_no_update
BEFORE UPDATE ON predictions
BEGIN
    SELECT RAISE(ABORT,
      'Las predicciones son inmutables. Registra una version nueva del modelo.');
END;

CREATE TRIGGER IF NOT EXISTS trg_pred_no_delete
BEFORE DELETE ON predictions
BEGIN
    SELECT RAISE(ABORT,
      'Las predicciones no se borran. Ese registro es lo que hace honesta la evaluacion.');
END;

-- ---------------------------------------------------------------------------
-- metrics: el marcador. Una fila por (modelo, mercado, conjunto evaluado).
-- Esta sí se recalcula: es derivada, no es un hecho.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics (
    model_version TEXT NOT NULL REFERENCES model_versions(model_version),
    market        TEXT NOT NULL,
    eval_set      TEXT NOT NULL,      -- 'all', '2425', 'walkforward'
    n_matches     INTEGER NOT NULL,
    log_loss      REAL,
    brier         REAL,
    accuracy      REAL,               -- solo contexto, no decide nada (regla 5)
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (model_version, market, eval_set)
);

-- calibration_bins: la curva de calibración, guardada en vez de recalculada
-- en cada carga del dashboard.
CREATE TABLE IF NOT EXISTS calibration_bins (
    model_version TEXT NOT NULL REFERENCES model_versions(model_version),
    market        TEXT NOT NULL,
    eval_set      TEXT NOT NULL,
    bin_low       REAL NOT NULL,      -- 0.0, 0.1, 0.2 ...
    bin_high      REAL NOT NULL,
    n             INTEGER NOT NULL,
    mean_pred     REAL,               -- lo que el modelo prometió
    observed_rate REAL,               -- lo que de verdad pasó
    PRIMARY KEY (model_version, market, eval_set, bin_low)
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Crea el esquema si no existe. Correrlo dos veces no rompe nada."""
    con = connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    return con
