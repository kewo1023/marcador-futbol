"""El gate de promocion: quien emite las predicciones manana.

LA REGLA, EN UNA LINEA
----------------------
El campeon conserva el titulo salvo que lo derroten de forma concluyente. Un
empate lo gana el campeon.

POR QUE ASI Y NO "GANA EL DEL MEJOR LOG-LOSS"
---------------------------------------------
Porque una diferencia pequena de log-loss no significa nada. En la F2 este
mismo proyecto declaro que el modelo "le ganaba a Elo por 0.0018" y resulto
ser ruido puro: el intervalo de confianza cruzaba cero de lado a lado.

Si el gate comparara promedios, promoveria un modelo cada vez que el azar le
diera una decima de ventaja. Y como promover es acumulativo, el sistema se
iria degradando a punta de mejoras imaginarias — que es exactamente el fallo
que esta fase existe para impedir. Reentrenar cada semana sin condicion es la
forma mas rapida de empeorar un modelo bueno.

LA COMPARACION ES ENTRE CONFIGURACIONES, NO ENTRE AJUSTES
---------------------------------------------------------
Campeon y retador se reajustan con el MISMO procedimiento sobre el MISMO
periodo. Si se comparara el campeon tal como esta hoy contra un retador recien
entrenado, el retador ganaria siempre por tener parametros mas frescos, y el
gate no estaria midiendo lo que cree medir.
"""
import csv
import datetime as dt
import json

from .backtest import ModelConfig
from .config import LEDGER_DIR
from .scoring import bootstrap_diff

CHAMPION_FILE = LEDGER_DIR / "champion.json"
CHALLENGES_FILE = LEDGER_DIR / "challenges.csv"

CHALLENGE_FIELDS = ["decided_at", "gate_seasons", "n_matches",
                    "champion", "challenger",
                    "champion_logloss", "challenger_logloss",
                    "diff", "ci_low", "ci_high", "p_value",
                    "decision", "reason"]

PROMOTE = "PROMOVIDO"
KEEP = "RECHAZADO"


def read_champion():
    """La configuracion que esta en produccion hoy. None si no hay ninguna."""
    if not CHAMPION_FILE.exists():
        return None
    d = json.loads(CHAMPION_FILE.read_text(encoding="utf-8"))
    return {"config": ModelConfig.from_dict(d["config"]), "raw": d}


def write_champion(cfg: ModelConfig, reason: str, previous: str | None = None):
    """Deja el campeon en el ledger, NO en el codigo.

    Vive en un archivo versionado y no en una constante de Python porque el
    gate corre solo, en un runner: si el modelo en produccion fuera codigo,
    promover exigiria que una persona editara un .py, y entonces el sistema no
    se estaria corrigiendo solo — estaria pidiendo permiso.

    Y al estar versionado, `git log ledger/champion.json` es el historial
    completo de que modelo emitio cada prediccion y desde cuando.
    """
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    CHAMPION_FILE.write_text(json.dumps({
        "model_version": cfg.slug(),
        "config": cfg.to_dict(),
        "promoted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "promoted_because": reason,
        "previous": previous,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_challenges():
    if not CHALLENGES_FILE.exists():
        return []
    with CHALLENGES_FILE.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def record_challenge(row):
    """Guarda TODOS los desafios, incluidos los rechazados.

    Los rechazos son la evidencia de que el gate hace algo. Un historial que
    solo muestra promociones es indistinguible de un sistema sin gate.
    """
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    rows = read_challenges() + [row]
    with CHALLENGES_FILE.open("w", encoding="utf-8", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=CHALLENGE_FIELDS)
        wr.writeheader()
        wr.writerows(rows)


def decide(champion_losses, challenger_losses, seed=0):
    """El veredicto. Devuelve (decision, razon, estadisticas).

    Tres desenlaces, y solo uno cambia algo:

      · el retador gana y el intervalo NO cruza cero  -> PROMOVIDO
      · el intervalo cruza cero (empate estadistico)  -> RECHAZADO
      · el retador pierde                             -> RECHAZADO

    Los dos ultimos dejan al campeon donde estaba. Es deliberadamente
    conservador: el costo de no promover una mejora real es perderse una
    ganancia pequena; el de promover una mejora imaginaria es degradar el
    sistema sin que nadie se entere.
    """
    diff, lo, hi, p, n = bootstrap_diff(challenger_losses, champion_losses,
                                        seed=seed)
    stats = {"diff": diff, "ci_low": lo, "ci_high": hi, "p_value": p,
             "n_matches": n}
    conclusive = (lo > 0) == (hi > 0)     # el intervalo no contiene cero

    if diff < 0 and conclusive:
        return PROMOTE, (f"gana por {abs(diff):.4f} de log-loss y el intervalo "
                         f"95% [{lo:+.4f}, {hi:+.4f}] no cruza cero"), stats
    if diff < 0:
        return KEEP, (f"queda por delante por {abs(diff):.4f} pero el intervalo "
                      f"[{lo:+.4f}, {hi:+.4f}] cruza cero: empate estadistico, "
                      f"y el empate lo gana el campeon"), stats
    return KEEP, (f"pierde por {diff:.4f} de log-loss"), stats
