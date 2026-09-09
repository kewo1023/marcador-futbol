"""Backtest walk-forward reutilizable, y la configuracion de un modelo.

Vivia dentro de scripts/03. Se saco al paquete porque el gate de promocion de
la F4 necesita exactamente lo mismo: entrenar con el pasado, predecir el
futuro, sin que se cuele una sola fila al reves.
"""
import datetime as dt
from dataclasses import dataclass, asdict

from . import dixon_coles as dc
from .baseline import OUTCOMES

# Cada cuantos dias se re-ajusta durante un backtest. Reajustar en cada partido
# seria mas fino y mucho mas lento; en una semana de futbol la liga casi no
# cambia.
REFIT_DAYS = 7


@dataclass(frozen=True)
class ModelConfig:
    """Los hiperparametros que definen un modelo. Lo que el gate compara.

    Es congelado (frozen) a proposito: una configuracion que ya emitio
    predicciones no se puede modificar en el sitio, igual que las predicciones
    mismas. Para cambiar algo se crea otra.
    """
    xi: float = 0.002        # decaimiento temporal
    reg: float = 0.002       # regularizacion hacia el promedio de la liga
    use_rho: bool = True     # correccion Dixon-Coles de marcadores bajos
    refit_days: int = REFIT_DAYS

    def slug(self) -> str:
        """Nombre estable y legible. Dos configuraciones iguales dan el mismo
        nombre, asi que no se puede registrar dos veces la misma con nombres
        distintos y comparar una contra si misma sin darse cuenta."""
        rho = "rho" if self.use_rho else "norho"
        return (f"dc-xi{int(round(self.xi * 10000)):04d}"
                f"-reg{int(round(self.reg * 1000)):03d}-{rho}")

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return ModelConfig(xi=float(d["xi"]), reg=float(d["reg"]),
                           use_rho=bool(d["use_rho"]),
                           refit_days=int(d.get("refit_days", REFIT_DAYS)))


def load_matches(con, league):
    rows = con.execute(
        """SELECT match_id, match_date, season, home_team, away_team,
                  fthg, ftag, ftr
           FROM matches WHERE league = ? AND ftr IS NOT NULL
           ORDER BY match_date, home_team""", (league,)).fetchall()
    return [{"id": r["match_id"], "date": dt.date.fromisoformat(r["match_date"]),
             "season": r["season"], "home": r["home_team"], "away": r["away_team"],
             "hg": r["fthg"], "ag": r["ftag"], "ftr": r["ftr"]} for r in rows]


def walk_forward(matches, target_seasons, cfg: ModelConfig):
    """Recorre el tiempo hacia adelante prediciendo solo con el pasado.

    Devuelve (predicciones, n_ajustes, n_con_equipo_desconocido), donde cada
    prediccion es (match_id, probs, fecha_del_dato_mas_reciente_usado).
    """
    targets = [m for m in matches if m["season"] in target_seasons]
    if not targets:
        return [], 0, 0

    out, fit, last_fit, n_fits, unknown = [], None, None, 0, 0
    for m in targets:
        if (fit is None or last_fit is None
                or (m["date"] - last_fit).days >= cfg.refit_days):
            # Estrictamente ANTERIORES. El '<' es la regla 4 entera.
            train = [t for t in matches if t["date"] < m["date"]]
            if not train:
                continue
            fit = dc.fit(train, m["date"], xi=cfg.xi, use_rho=cfg.use_rho,
                         reg=cfg.reg, warm_start=fit)
            last_fit = m["date"]
            n_fits += 1
            fit.last_data_date = max(t["date"] for t in train)

        if not fit.knows(m["home"]) or not fit.knows(m["away"]):
            unknown += 1
        out.append((m["id"], fit.probs_1x2(m["home"], m["away"]),
                    fit.last_data_date.isoformat()))
    return out, n_fits, unknown


def per_match_logloss(preds, matches):
    """log-loss de cada partido por separado, alineado con `matches`.

    Se devuelve por partido y no promediado porque el gate necesita comparar
    dos modelos PARTIDO A PARTIDO: promediar primero tira la informacion que
    hace posible saber si la diferencia es real o es ruido.
    """
    import math
    by_id = {mid: p for mid, p, _ in preds}
    ids, losses = [], []
    for m in matches:
        p = by_id.get(m["id"])
        if not p or len(p) != len(OUTCOMES):
            continue
        ids.append(m["id"])
        losses.append(-math.log(max(p[m["ftr"]], 1e-15)))
    return ids, losses


def evaluate_config(matches, target_seasons, cfg: ModelConfig):
    """Corre el backtest de una configuracion y devuelve (ids, perdidas)."""
    preds, _, _ = walk_forward(matches, target_seasons, cfg)
    targets = [m for m in matches if m["season"] in target_seasons]
    return per_match_logloss(preds, targets)


def load_market_matches(con, league, market):
    """Los partidos con la columna del evento que pide el mercado.

    El motor no sabe que esta contando: recibe hg/ag y ajusta. Cambiar de
    mercado es cambiar de que columna salen esos dos numeros, y nada mas. Ese
    era el argumento para escribir Dixon-Coles a mano en la F2, y esta funcion
    es donde se cobra.
    """
    rows = con.execute(
        f'''SELECT match_id, match_date, season, home_team, away_team,
                   "{market.home_col}" AS hg, "{market.away_col}" AS ag,
                   avgc_o25, avgc_u25
            FROM matches
            WHERE league = ? AND ftr IS NOT NULL
              AND "{market.home_col}" IS NOT NULL AND "{market.away_col}" IS NOT NULL
            ORDER BY match_date, home_team''', (league,)).fetchall()
    return [{"id": r["match_id"], "date": dt.date.fromisoformat(r["match_date"]),
             "season": r["season"], "home": r["home_team"], "away": r["away_team"],
             "hg": r["hg"], "ag": r["ag"], "total": r["hg"] + r["ag"],
             "avgc_o25": r["avgc_o25"], "avgc_u25": r["avgc_u25"]} for r in rows]


def walk_forward_market(matches, target_seasons, cfg: ModelConfig, lines):
    """Walk-forward para over/under de cualquier evento.

    Un solo ajuste sirve para todas las lineas: la distribucion de conteos ya
    esta completa, y cada linea es solo una forma distinta de sumar sus
    celdas. Por eso agregar lineas es gratis y agregar mercados cuesta un
    backtest.
    """
    targets = [m for m in matches if m["season"] in target_seasons]
    if not targets:
        return {}, 0

    out = {line: {} for line in lines}
    fit, last_fit, n_fits = None, None, 0
    for m in targets:
        if (fit is None or last_fit is None
                or (m["date"] - last_fit).days >= cfg.refit_days):
            train = [t for t in matches if t["date"] < m["date"]]
            if not train:
                continue
            fit = dc.fit(train, m["date"], xi=cfg.xi, use_rho=cfg.use_rho,
                         reg=cfg.reg, warm_start=fit)
            last_fit = m["date"]
            n_fits += 1
        for line in lines:
            out[line][m["id"]] = fit.probs_over_under_line(m["home"], m["away"], line)
    return out, n_fits
