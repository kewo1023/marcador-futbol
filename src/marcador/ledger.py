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

from .config import (LEDGER_CALENDAR, LEDGER_DIR, LEDGER_FIXTURES, LEDGER_HEALTH,
                     LEDGER_METRICS, LEDGER_MISSED, LEDGER_PREDICTIONS,
                     LEDGER_MARKET_PRE, LEDGER_POSTPONED, LEDGER_RESULTS,
                     LEDGER_RESULTS_HEALTH)

PRED_FIELDS = ["match_id", "match_date", "home_team", "away_team",
               "model_version", "market", "outcome", "prob", "mode",
               "info_cutoff", "created_at"]
# market_*: la probabilidad implicita de la cuota de CIERRE (promedio de casas,
# sin margen), no la cuota. Es el techo contra el que se mide el modelo, y
# guardarlo junto al resultado es lo que permite decir, partido a partido y
# desde el ledger solo, si el modelo puso mas o menos que el mercado en lo que
# paso. Es un dato derivado (regla 2): ni la cuota cruda ni la de ninguna casa.
# yellows: total de amarillas del partido, para evaluar el mercado de tarjetas.
# market_o25 / market_u25: la probabilidad implicita de la cuota de cierre de
# over/under 2.5 goles, sin margen — el techo del unico mercado over/under que
# lo tiene. Vacios si la fuente no los trae para ese partido.
# sot: total de tiros a puerta del partido, para ese mercado.
# score_source: de donde llego el marcador primero ('api' = football-data.org,
# 'csv' = football-data.co.uk). completed_at: cuando football-data.co.uk
# completo la fila con cuota, tarjetas y tiros (vacio mientras no lo haga).
RESULT_FIELDS = ["match_id", "match_date", "home_team", "away_team",
                 "fthg", "ftag", "ftr", "market_h", "market_d", "market_a",
                 "market_o25", "market_u25", "yellows", "sot", "recorded_at",
                 "score_source", "completed_at"]
# Lo que football-data.co.uk puede COMPLETAR en una fila que ya tiene marcador.
RESULT_COMPLETABLE = ["market_h", "market_d", "market_a", "market_o25",
                      "market_u25", "yellows", "sot"]
METRIC_FIELDS = ["model_version", "market", "eval_set", "n_matches",
                 "log_loss", "brier", "accuracy", "computed_at"]
MISSED_FIELDS = ["match_id", "match_date", "home_team", "away_team",
                 "ftr", "detected_at"]
# prov_score: el marcador segun la fuente de FIXTURES ('1-0'), provisional.
# Vive aqui y no en results.csv a proposito: este archivo es el que cambia; el
# de resultados es el que cuenta, y solo lo escribe 05_score desde la fuente
# de resultados. Vacio hasta que la fuente de fixtures lo publique.
FIXTURE_FIELDS = ["match_id", "match_date", "kickoff_utc", "home_team",
                  "away_team", "prov_score", "updated_at"]
# checked_at: cuando se miro. upcoming/unconfirmed: partidos en la ventana y
# cuantos sin hora. file_age_hours: cuanto llevaba el archivo sin regenerarse.
# error: que fallo al bajar, si algo. unknown_teams: nombres sin alias.
HEALTH_FIELDS = ["checked_at", "league", "upcoming", "unconfirmed",
                 "file_last_date", "file_age_hours", "error", "unknown_teams"]
# La fuente de resultados. played: partidos con resultado en el archivo de la
# temporada. file_last_date: la fecha del ultimo partido con resultado, o sea
# hasta donde llega la fuente. file_age_hours: cuanto llevaba el archivo sin
# regenerarse (vacio si la fuente no mando Last-Modified). awaiting: partidos
# predichos cuyo kickoff ya paso y que la fuente todavia no trae.
RESULTS_HEALTH_FIELDS = ["checked_at", "league", "played", "file_last_date",
                         "file_age_hours", "awaiting", "error"]


def _read(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, fields, rows):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    blank = {f: "" for f in fields}
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        # Filas escritas antes de que existiera una columna no la tienen.
        wr.writerows({**blank, **r} for r in rows)


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
    jugado. Lo que no cambia nunca es un resultado ya registrado.

    Desde el 2026-09-14 el marcador puede llegar primero por la API
    (football-data.org) y la cuota de cierre, las tarjetas y los tiros
    despues, por football-data.co.uk. Esa segunda llegada COMPLETA columnas
    vacias de la misma fila; no toca el marcador ni `recorded_at`. Dos
    marcadores distintos para el mismo partido abortan: es la senal de que
    una de las dos fuentes esta mal, y eso lo mira una persona.
    """
    by_id = {r["match_id"]: r for r in read_results()}
    changed = 0
    for r in rows:
        old = by_id.get(r["match_id"])
        if old and (old["ftr"], old["fthg"], old["ftag"]) != \
                   (r["ftr"], str(r["fthg"]), str(r["ftag"])):
            raise ValueError(
                f"El resultado de {r['match_id']} ya estaba registrado como "
                f"{old['fthg']}-{old['ftag']} y ahora llega "
                f"{r['fthg']}-{r['ftag']}. Revisar la fuente a mano.")
        if old:
            # Mismo marcador. Solo se completa lo que estaba vacio y ahora
            # viene lleno. Filas anteriores a una columna no la tienen (get).
            fill = {c: r[c] for c in RESULT_COMPLETABLE
                    if not old.get(c) and r.get(c) not in ("", None)}
            if not fill:
                continue
            merged = {**old, **fill}
            if any(k.startswith("market") for k in fill) or "yellows" in fill or "sot" in fill:
                merged["completed_at"] = r.get("completed_at") or r["recorded_at"]
            by_id[r["match_id"]] = merged
            changed += 1
            continue
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


def read_fixtures():
    return _read(LEDGER_FIXTURES)


def upsert_fixtures(rows) -> int:
    """La hora y la fecha de los partidos por jugar. Devuelve cuantos cambiaron.

    A diferencia de las predicciones, esto SI se actualiza: un partido que se
    aplaza cambia de hora y de dia, y el ledger tiene que decir la ultima que
    se supo. Lo que nunca cambia es el match_id — ese lleva la fecha con la
    que se emitio la prediccion, y si un partido se mueve de dia, el resultado
    va a llegar con otra fecha y otro id. Ese caso lo detecta 04_predict.py y
    lo deja en postponed.csv (ver record_postponed).
    """
    by_id = {r["match_id"]: r for r in read_fixtures()}
    changed = 0
    for r in rows:
        old = by_id.get(r["match_id"])
        if old and (old["kickoff_utc"], old["match_date"]) == \
                   (r["kickoff_utc"] or "", r["match_date"]):
            continue
        # El marcador provisional que ya hubiera se conserva: esta funcion
        # solo sabe de horas.
        by_id[r["match_id"]] = {**r, "kickoff_utc": r["kickoff_utc"] or "",
                                "prov_score": (old or {}).get("prov_score") or ""}
        changed += 1
    if changed:
        _write_fixtures(by_id)
    return changed


def _write_fixtures(by_id):
    rows = [{**{"prov_score": ""}, **r} for r in by_id.values()]
    _write(LEDGER_FIXTURES, FIXTURE_FIELDS,
           sorted(rows, key=lambda x: (x["match_date"], x["match_id"])))


def update_provisional(scores: dict) -> int:
    """Escribe el marcador provisional de los partidos que ya estan en
    fixtures.csv y que la fuente de fixtures da por jugados. Devuelve cuantos
    cambiaron. Solo toca partidos ya registrados: este archivo no es una
    copia de la fuente, es la hora (y ahora el marcador) de lo predicho."""
    by_id = {r["match_id"]: r for r in read_fixtures()}
    changed = 0
    for mid, score in scores.items():
        r = by_id.get(mid)
        if r is None or (r.get("prov_score") or "") == score:
            continue
        r["prov_score"] = score
        changed += 1
    if changed:
        _write_fixtures(by_id)
    return changed


def read_health():
    return _read(LEDGER_HEALTH)


def append_health(rows) -> int:
    """Una fila por corrida y liga. Append puro: es una serie de tiempo, y
    dos corridas iguales seguidas son un dato (la fuente no cambio), no un
    duplicado."""
    if not rows:
        return 0
    _write(LEDGER_HEALTH, HEALTH_FIELDS, read_health() + list(rows))
    return len(rows)


def read_results_health():
    return _read(LEDGER_RESULTS_HEALTH)


def append_results_health(rows) -> int:
    """Una fila por corrida de 05_score y liga. Append puro, como
    source_health: es una serie de tiempo de cuando publica la fuente."""
    if not rows:
        return 0
    _write(LEDGER_RESULTS_HEALTH, RESULTS_HEALTH_FIELDS,
           read_results_health() + list(rows))
    return len(rows)


# Cuotas pre-partido. pre_*: probabilidad implicita sin margen del promedio
# de casas antes del kickoff; file_modified: cuando la fuente escribio el
# archivo del que salio (la prueba de que es de antes del partido).
PRE_FIELDS = ["match_id", "match_date", "home_team", "away_team",
              "pre_h", "pre_d", "pre_a", "pre_o25", "pre_u25",
              "file_modified", "fetched_at"]
PRE_VALUE_COLS = ["pre_h", "pre_d", "pre_a", "pre_o25", "pre_u25"]


def read_market_pre():
    return _read(LEDGER_MARKET_PRE)


def latest_market_pre():
    """La ultima opinion registrada del mercado por partido."""
    out = {}
    for r in read_market_pre():
        out[r["match_id"]] = r
    return out


def append_market_pre(rows) -> int:
    """Agrega solo las filas cuya opinion del mercado CAMBIO respecto a la
    ultima registrada para ese partido. Seis corridas al dia sobre un archivo
    que no se regenero son un dato, no seis. Devuelve cuantas entraron."""
    last = latest_market_pre()
    new = [r for r in rows
           if r["match_id"] not in last
           or any(last[r["match_id"]][c] != r[c] for c in PRE_VALUE_COLS)]
    if new:
        _write(LEDGER_MARKET_PRE, PRE_FIELDS, read_market_pre() + new)
    return len(new)


def read_missed():
    return _read(LEDGER_MISSED)


def record_missed(rows) -> int:
    """Registra partidos que se jugaron SIN que el sistema los predijera.

    Se guardan en vez de solo avisarse, y se versionan, por la misma razon que
    las predicciones: un agujero en el track record que solo existe en el log
    de un job que ya expiro no es un agujero documentado, es un agujero
    invisible. Quien audite el proyecto tiene que poder ver que faltan estos
    partidos y no suponer que se predijo todo.
    """
    known = {r["match_id"] for r in read_missed()}
    fresh = [r for r in rows if r["match_id"] not in known]
    if not fresh:
        return 0
    _write(LEDGER_MISSED, MISSED_FIELDS,
           sorted(read_missed() + fresh, key=lambda r: r["match_date"]))
    return len(fresh)


# Aplazamientos. old_match_id: la prediccion emitida para la fecha original.
# new_match_id: el id con la fecha nueva segun la fuente de fixtures.
# new_kickoff_utc: la hora nueva, vacia si la liga no la ha confirmado.
# old_kickoff_utc: la hora con la que se predijo. Vacia quiere decir que la
# fecha original era provisional (la fuente escribe 00:00 cuando la liga no
# confirmo): no se aplazo un partido, se corrigio una fecha que nunca fue firme.
POSTPONED_FIELDS = ["old_match_id", "old_kickoff_utc", "new_match_id",
                    "new_kickoff_utc", "detected_at"]


def read_postponed():
    return _read(LEDGER_POSTPONED)


def latest_postponed():
    """{old_match_id: fila} con la ultima fecha nueva que se supo."""
    out = {}
    for r in read_postponed():
        out[r["old_match_id"]] = r
    return out


def record_postponed(rows) -> int:
    """Registra partidos predichos que la fuente movio a otra fecha.

    POR QUE EXISTE: el match_id lleva la fecha. Un partido aplazado vuelve con
    otro id, y la prediccion emitida para la fecha original queda con kickoff
    pasado y sin resultado nunca: el dashboard la contaria "esperando
    resultado" para siempre. Corregirla no se puede (regla 3), y tampoco hace
    falta: se anota aqui a donde se movio.

    QUE PASA CON ESA PREDICCION depende de si la fecha original era firme:

    · Aplazamiento (se predijo con hora confirmada): no se evalua nunca. Se
      emitio para un partido que ese dia no se jugo, con la informacion de ese
      dia; el partido se predice de nuevo con el id nuevo, y esa cuenta.
    · Fecha provisional corregida (se predijo sin hora): SI se evalua, contra
      el resultado del id real. Es el mismo partido, predicho antes de jugarse;
      lo unico mal era la fecha que la fuente puso de comodin. Ver
      provisional_aliases para las dos condiciones.

    En ningun caso se toca predictions.csv. Si un resultado llegara con el id
    viejo, el partido si se jugo en su fecha, y el resultado manda.

    Append de cambios, como market_pre: entra una fila solo si el id nuevo o su
    hora cambiaron respecto a la ultima registrada para ese partido (uno que se
    aplaza dos veces deja dos filas). La ultima es la que vale.
    """
    last = latest_postponed()
    new = [r for r in rows
           if r["old_match_id"] not in last
           or (last[r["old_match_id"]]["new_match_id"],
               last[r["old_match_id"]]["new_kickoff_utc"])
           != (r["new_match_id"], r["new_kickoff_utc"] or "")]
    if new:
        _write(LEDGER_POSTPONED, POSTPONED_FIELDS,
               read_postponed() + [{**r, "new_kickoff_utc": r["new_kickoff_utc"] or ""}
                                   for r in new])
    return len(new)


def provisional_aliases(preds=None, postponed=None) -> dict:
    """{id viejo: id real} de las predicciones con fecha provisional que se
    evaluan contra el resultado del id real.

    Una fila de postponed.csv sin old_kickoff_utc dice que la fecha con que se
    predijo nunca fue firme. Esa prediccion cuenta como la del partido real
    si se cumplen las dos:

    · Se emitio antes del kickoff real (la regla 3 aplicada al partido que de
      verdad se jugo). Sin hora real confirmada, antes del inicio de ese dia.
    · El id real no tiene prediccion propia. Si la tiene, cuenta esa: es la
      que se emitio con la fecha correcta y mas cerca del partido, y evaluar
      las dos seria contar el mismo partido dos veces.

    Un solo lugar para la regla, porque la usan 05_score (que resultados
    buscar, que cuenta y que no es un partido sin prediccion) y el dashboard.
    """
    preds = read_predictions() if preds is None else preds
    postponed = latest_postponed() if postponed is None else postponed
    created, predicted = {}, set()
    for p in preds:
        if p["mode"] != "live":
            continue
        predicted.add(p["match_id"])
        created[p["match_id"]] = max(created.get(p["match_id"], ""), p["created_at"])
    out = {}
    for old, r in postponed.items():
        new = r["new_match_id"]
        if r.get("old_kickoff_utc") or old not in created or new in predicted:
            continue
        kickoff = r.get("new_kickoff_utc") or new.split("_")[1] + "T00:00"
        if created[old][:16] < kickoff:
            out[old] = new
    return out


# Un paron por fila. last_match: el ultimo dia con partido antes del hueco;
# next_match: el primero despues. idle_days: dias enteros sin partido entre
# los dos. league es el codigo de liga, o ALL para el hueco en que ninguna de
# las cinco juega (la firma de una fecha FIFA).
CALENDAR_FIELDS = ["league", "last_match", "next_match", "idle_days",
                   "computed_at"]


def read_calendar():
    return _read(LEDGER_CALENDAR)


def write_calendar(rows) -> bool:
    """Reescribe el archivo SOLO si algun paron cambio. computed_at no cuenta
    como cambio: seis corridas al dia sobre el mismo calendario no son seis
    commits. Devuelve True si escribio."""
    def key(rs):
        return [tuple(r[f] for f in CALENDAR_FIELDS[:-1]) for r in rs]
    rows = list(rows)
    if key(read_calendar()) == key(rows):
        return False
    _write(LEDGER_CALENDAR, CALENDAR_FIELDS, rows)
    return True
