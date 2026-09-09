"""El ledger: las predicciones en texto plano, versionadas en git.

POR QUE EXISTE
--------------
La base SQLite vive en data/, que esta en .gitignore, y el runner de GitHub
Actions se destruye cuando termina el job. Si las predicciones vivieran solo
ahi, cada corrida empezaria en blanco y no habria registro de nada.

Podrian commitearse la base entera, pero es un binario (diffs ilegibles) y
lleva el volcado crudo de la fuente, que la regla 2 prohibe republicar. El
ledger guarda solo lo derivado: que predijo el modelo, que paso, y como le fue.

EL EFECTO SECUNDARIO QUE VALE MAS QUE EL ORIGINAL
-------------------------------------------------
Al estar versionado, la fecha del commit que agrego una prediccion es prueba
externa de cuando se emitio. Una columna created_at la escribe el propio
sistema que se esta evaluando; un commit firmado por el reloj de GitHub, no.
Cualquiera puede auditar el proyecto con `git log` sin confiar en nosotros.

APPEND-ONLY
-----------
Una fila escrita no se reescribe nunca. Si una prediccion ya esta en el
ledger, un intento de volver a escribirla se ignora en silencio; un intento de
escribirla con OTRA probabilidad levanta una excepcion, porque eso significa
que algo trato de cambiar el pasado.
"""
import csv
import datetime as dt
from pathlib import Path

from .config import (LEDGER_DIR, LEDGER_METRICS, LEDGER_PREDICTIONS,
                     LEDGER_RESULTS)

PRED_FIELDS = ["match_id", "match_date", "home_team", "away_team",
               "model_version", "market", "outcome", "prob", "mode",
               "info_cutoff", "created_at"]
RESULT_FIELDS = ["match_id", "match_date", "home_team", "away_team",
                 "fthg", "ftag", "ftr", "recorded_at"]
METRIC_FIELDS = ["model_version", "market", "eval_set", "n_matches",
                 "log_loss", "brier", "accuracy", "computed_at"]


def _read(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, fields, rows):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)


def read_predictions():
    return _read(LEDGER_PREDICTIONS)


def read_results():
    return _read(LEDGER_RESULTS)


def predicted_keys():
    """Las predicciones que ya existen, para no volver a emitirlas."""
    return {(r["match_id"], r["model_version"], r["market"], r["outcome"]): r
            for r in read_predictions()}


def predicted_matches(model_version=None):
    return {r["match_id"] for r in read_predictions()
            if model_version is None or r["model_version"] == model_version}


def append_predictions(rows) -> int:
    """Agrega filas nuevas. Devuelve cuantas se agregaron de verdad.

    Una fila identica a una existente se ignora (la corrida diaria vuelve a
    ver los mismos partidos y eso es normal). Una fila que contradice a una
    existente ABORTA: si la probabilidad cambio, alguien esta reescribiendo el
    pasado, y eso es justo lo que el proyecto entero existe para impedir.
    """
    existing = predicted_keys()
    fresh = []
    for r in rows:
        key = (r["match_id"], r["model_version"], r["market"], r["outcome"])
        old = existing.get(key)
        if old is None:
            fresh.append(r)
            existing[key] = r
            continue
        if abs(float(old["prob"]) - float(r["prob"])) > 1e-9:
            raise ValueError(
                f"INMUTABILIDAD VIOLADA en {key}: el ledger dice "
                f"{old['prob']} y se intento escribir {r['prob']}. "
                f"Una prediccion emitida no se corrige; se registra una "
                f"version nueva del modelo.")
    if not fresh:
        return 0
    _write(LEDGER_PREDICTIONS, PRED_FIELDS, read_predictions() + fresh)
    return len(fresh)


def upsert_results(rows) -> int:
    """Los resultados si se pueden completar: un partido pasa de sin jugar a
    jugado. Lo que no cambia nunca es un resultado ya registrado."""
    by_id = {r["match_id"]: r for r in read_results()}
    changed = 0
    for r in rows:
        old = by_id.get(r["match_id"])
        if old and (old["ftr"], old["fthg"], old["ftag"]) == \
                   (r["ftr"], str(r["fthg"]), str(r["ftag"])):
            continue
        if old:
            raise ValueError(
                f"El resultado de {r['match_id']} ya estaba registrado como "
                f"{old['fthg']}-{old['ftag']} y ahora llega "
                f"{r['fthg']}-{r['ftag']}. Revisar la fuente a mano.")
        by_id[r["match_id"]] = r
        changed += 1
    if changed:
        _write(LEDGER_RESULTS, RESULT_FIELDS,
               sorted(by_id.values(), key=lambda x: (x["match_date"], x["match_id"])))
    return changed


def upsert_metrics(rows):
    """Las metricas SI se reescriben: son derivadas, no son un hecho.

    Se actualizan por (modelo, mercado, conjunto). El merge en vez del
    reemplazo total importa porque conviven dos cosas en el mismo archivo: las
    metricas del backtest, que escribe el script 03 de vez en cuando, y las del
    track record en vivo, que se recalculan a diario. Reescribir el archivo
    entero desde el job diario borraria las primeras.
    """
    existing = {(r["model_version"], r["market"], r["eval_set"]): r
                for r in _read(LEDGER_METRICS)}
    for r in rows:
        existing[(r["model_version"], r["market"], r["eval_set"])] = r
    _write(LEDGER_METRICS, METRIC_FIELDS,
           sorted(existing.values(),
                  key=lambda r: (r["eval_set"], float(r["log_loss"] or 9))))


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
