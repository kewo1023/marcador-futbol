"""Motor Poisson y sus dos ajustes Dixon-Coles.

QUE ESTIMA ESTE MODELO
----------------------
No estima "quien gana". Estima cuantos goles marca cada equipo, y de ahi sale
todo lo demas. Cada equipo tiene dos numeros:

    ataque[i]   cuanto marca por encima o por debajo del promedio de la liga
    defensa[i]  cuanto le marcan por encima o por debajo del promedio

Mas un tercero, comun a toda la liga:

    localia     cuanto sube el marcador del que juega en casa

Con eso se arma la tasa de goles esperada de cada lado:

    lambda (local)     = exp(ataque[local]  + defensa[visitante] + localia)
    mu     (visitante) = exp(ataque[visitante] + defensa[local])

El exp() esta ahi para que las tasas nunca salgan negativas y para que los
parametros se sumen en vez de multiplicarse, que es mas facil de ajustar.
Un ataque de 0 es "exactamente el promedio de la liga"; 0.30 es un equipo que
marca ~35% mas que el promedio.

En Excel: es una tabla con dos columnas por equipo, mas una celda de localia,
y una formula que combina la fila del local con la del visitante. Lo que hace
el ajuste es buscar los valores de esas columnas que mejor explican los
marcadores que de verdad ocurrieron.

POR QUE ESTO Y NO UN CLASIFICADOR DE 1X2
----------------------------------------
Porque de lambda y mu sale la distribucion completa de marcadores, y de ahi
salen TODOS los mercados: 1X2, over/under, BTTS, y en la F5 corners, tarjetas
y tiros con el mismo codigo apuntado a otra columna. Un clasificador de 1X2
entrenado directamente da el resultado y nada mas.

LOS DOS AJUSTES DE DIXON-COLES
------------------------------
El Poisson puro tiene dos defectos conocidos, y Dixon-Coles (1997) corrige
ambos. Este modulo los deja separables a proposito, para poder medir cuanto
aporta cada uno por su cuenta.

  1. rho  — el Poisson asume que los goles de los dos equipos son
     independientes, y no lo son: en los marcadores bajos (0-0, 1-0, 0-1, 1-1)
     hay mas correlacion de la que el modelo predice. rho reajusta justo esas
     cuatro casillas y deja el resto igual.

  2. xi   — el Poisson trata igual un partido de hace cinco temporadas y uno
     de la semana pasada. xi hace que el peso de cada partido caiga de forma
     exponencial con la antiguedad. Es la unica via por la que el modelo se
     entera de que un equipo cambio.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# Cotas de rho. Fuera de este rango la correccion empieza a producir
# probabilidades negativas en las casillas bajas.
RHO_BOUNDS = (-0.25, 0.25)
TAU_FLOOR = 1e-10


class DixonColesFit:
    """El resultado de un ajuste: los parametros y con que datos se obtuvieron."""

    def __init__(self, teams, attack, defense, home_adv, rho, xi,
                 n_matches, info_cutoff, converged):
        self.teams = teams
        self.index = {t: i for i, t in enumerate(teams)}
        self.attack = attack
        self.defense = defense
        self.home_adv = home_adv
        self.rho = rho
        self.xi = xi
        self.n_matches = n_matches
        self.info_cutoff = info_cutoff   # ultima fecha que el modelo vio
        self.converged = converged

    def knows(self, team):
        return team in self.index

    def rates(self, home, away):
        """Devuelve (lambda, mu): goles esperados de local y de visitante.

        Un equipo que el modelo nunca vio (recien ascendido, primera temporada
        de la ventana) entra como equipo promedio: ataque y defensa en 0. Es
        una aproximacion mala a proposito y conocida — los ascendidos suelen
        ser peores que el promedio — y queda contada aparte para que la F4
        pueda diagnosticarla en vez de que se pierda en el promedio general.
        """
        ih, ia = self.index.get(home), self.index.get(away)
        att_h = self.attack[ih] if ih is not None else 0.0
        def_h = self.defense[ih] if ih is not None else 0.0
        att_a = self.attack[ia] if ia is not None else 0.0
        def_a = self.defense[ia] if ia is not None else 0.0
        lam = np.exp(att_h + def_a + self.home_adv)
        mu = np.exp(att_a + def_h)
        return float(lam), float(mu)

    def score_matrix(self, home, away, max_goals=10):
        """La distribucion completa de marcadores, como una matriz 11x11.

        La celda [x][y] es la probabilidad de que el partido termine x-y. De
        esta matriz sale cualquier mercado sumando las celdas que correspondan:
        la diagonal es el empate, el triangulo inferior es victoria local, y
        las anti-diagonales son los over/under.
        """
        lam, mu = self.rates(home, away)
        # Producto exterior: P(x goles del local) x P(y goles del visitante),
        # asumiendo independencia. El paso siguiente corrige esa suposicion.
        px = poisson.pmf(np.arange(max_goals + 1), lam)
        py = poisson.pmf(np.arange(max_goals + 1), mu)
        m = np.outer(px, py)

        if self.rho:
            # La correccion Dixon-Coles toca SOLO las cuatro casillas bajas.
            m[0, 0] *= 1.0 - lam * mu * self.rho
            m[0, 1] *= 1.0 + lam * self.rho
            m[1, 0] *= 1.0 + mu * self.rho
            m[1, 1] *= 1.0 - self.rho
            m = np.clip(m, 0.0, None)

        # La correccion rompe la normalizacion (las celdas ya no suman 1), y
        # truncar en max_goals tambien deja fuera una cola diminuta. Se
        # renormaliza para que lo que salga sean probabilidades de verdad.
        return m / m.sum()

    def probs_1x2(self, home, away, max_goals=10):
        m = self.score_matrix(home, away, max_goals)
        return {
            "H": float(np.tril(m, -1).sum()),   # local marca mas: bajo la diagonal
            "D": float(np.trace(m)),            # la diagonal es el empate
            "A": float(np.triu(m, 1).sum()),    # sobre la diagonal
        }

    def probs_over_under(self, home, away, line=2.5, max_goals=10):
        """Gratis: sale de la misma matriz. Es el anticipo de la F5."""
        m = self.score_matrix(home, away, max_goals)
        idx = np.arange(max_goals + 1)
        totals = idx[:, None] + idx[None, :]
        over = float(m[totals > line].sum())
        return {"OVER": over, "UNDER": 1.0 - over}

    def probs_btts(self, home, away, max_goals=10):
        """Gratis, tambien: 'ambos marcan' es todo menos la fila 0 y la col 0."""
        m = self.score_matrix(home, away, max_goals)
        yes = float(m[1:, 1:].sum())
        return {"YES": yes, "NO": 1.0 - yes}


# --- El ajuste ---------------------------------------------------------------

def _unpack(params, n_teams):
    """Convierte el vector plano del optimizador en parametros con nombre.

    El ataque tiene n-1 valores libres y el ultimo se deduce como menos la
    suma de los demas. Eso impone sum(ataque) = 0, que es lo que hace al
    modelo identificable: sin esa restriccion se le puede sumar una constante
    a todos los ataques y restarsela a todas las defensas sin cambiar ni una
    prediccion, y el optimizador se queda vagando por esa direccion plana.
    """
    att_free = params[:n_teams - 1]
    attack = np.concatenate([att_free, [-att_free.sum()]])
    defense = params[n_teams - 1:2 * n_teams - 1]
    home_adv = params[2 * n_teams - 1]
    rho = params[2 * n_teams]
    return attack, defense, home_adv, rho


def _tau(x, y, lam, mu, rho):
    """La correccion de las cuatro casillas bajas, vectorizada.

    Devuelve 1.0 para todo marcador que no sea 0-0, 0-1, 1-0 o 1-1, o sea que
    para la gran mayoria de partidos no hace absolutamente nada.
    """
    t = np.ones_like(lam)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t[m00] = 1.0 - lam[m00] * mu[m00] * rho
    t[m01] = 1.0 + lam[m01] * rho
    t[m10] = 1.0 + mu[m10] * rho
    t[m11] = 1.0 - rho
    return t


def _tau_derivs(x, y, lam, mu, rho):
    """Derivadas parciales de tau respecto a lambda, mu y rho.

    Solo son distintas de cero en las cuatro casillas bajas, igual que tau.
    """
    dl = np.zeros_like(lam); dm = np.zeros_like(lam); dr = np.zeros_like(lam)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    dl[m00] = -mu[m00] * rho;  dm[m00] = -lam[m00] * rho; dr[m00] = -lam[m00] * mu[m00]
    dl[m01] = rho;                                        dr[m01] = lam[m01]
    dm[m10] = rho;                                        dr[m10] = mu[m10]
    dr[m11] = -1.0
    return dl, dm, dr


def _neg_log_likelihood(params, n_teams, hi, ai, x, y, w, use_rho, reg=0.0):
    """Que tan mal explican estos parametros los marcadores que ocurrieron,
    y en que direccion habria que moverlos. Devuelve (valor, gradiente).

    El optimizador busca el minimo de esta funcion. Para un Poisson, la
    contribucion de un partido es  x*log(lambda) - lambda  por cada lado; el
    log(tau) del frente es el ajuste Dixon-Coles, y w es el peso por antiguedad.

    POR QUE EL GRADIENTE VA ESCRITO A MANO. Sin el, scipy lo estima moviendo
    cada parametro un poquito y midiendo el cambio: con 69 parametros son ~70
    evaluaciones por iteracion, y el tope interno de scipy (maxfun=15000) se
    agota a las ~190 iteraciones, antes de converger. Con el gradiente
    analitico es UNA evaluacion por iteracion: converge de verdad y el backtest
    completo pasa de horas a minutos.

    QUE HACE reg (REGULARIZACION). Suma un castigo proporcional al cuadrado de
    cada parametro de ataque y defensa. El efecto es asimetrico y es justo el
    que se busca: a un equipo con muchos partidos el castigo apenas lo mueve,
    porque los datos mandan; a un equipo con casi ningun partido con peso —un
    recien ascendido bajo decaimiento temporal— lo empuja hacia 0, que es
    "equipo promedio de la liga".

    Sin esto, un equipo del que el modelo casi no sabe nada recibe parametros
    extremos estimados sobre aire, y el modelo emite cosas como 0.7% a un
    resultado que despues ocurre. log-loss cobra esos casos carisimo: un solo
    partido asi pesa mas que cien predicciones buenas.
    """
    attack, defense, home_adv, rho = _unpack(params, n_teams)
    if not use_rho:
        rho = 0.0

    lam = np.exp(attack[hi] + defense[ai] + home_adv)
    mu = np.exp(attack[ai] + defense[hi])

    if use_rho:
        tau = np.clip(_tau(x, y, lam, mu, rho), TAU_FLOOR, None)
        dtau_dl, dtau_dm, dtau_dr = _tau_derivs(x, y, lam, mu, rho)
        log_tau = np.log(tau)
    else:
        tau = np.ones_like(lam)
        dtau_dl = dtau_dm = dtau_dr = np.zeros_like(lam)
        log_tau = np.zeros_like(lam)

    nll = -np.sum(w * (log_tau + x * np.log(lam) - lam + y * np.log(mu) - mu))

    # El castigo se escala por el peso total de los datos para que el mismo
    # valor de reg signifique lo mismo con y sin decaimiento temporal: sin la
    # escala, subir xi (que reduce el peso total) volveria la regularizacion
    # relativamente mas fuerte sin haberla tocado.
    scale = reg * w.sum()
    if reg:
        nll += scale * (np.sum(attack ** 2) + np.sum(defense ** 2))

    # Derivada respecto a las TASAS. Como lambda = exp(suma de parametros), la
    # regla de la cadena hacia cada parametro es simplemente multiplicar por la
    # propia lambda: d(lambda)/d(cualquiera de sus parametros) = lambda.
    g_lam = w * ((dtau_dl / tau) + x / lam - 1.0) * lam
    g_mu = w * ((dtau_dm / tau) + y / mu - 1.0) * mu

    # Cada equipo acumula lo que le toca como local y como visitante.
    # bincount suma por grupo: es el equivalente de un SUMAR.SI por equipo.
    g_att = (np.bincount(hi, g_lam, n_teams) + np.bincount(ai, g_mu, n_teams))
    g_def = (np.bincount(ai, g_lam, n_teams) + np.bincount(hi, g_mu, n_teams))
    if reg:
        g_att = g_att - 2.0 * scale * attack
        g_def = g_def - 2.0 * scale * defense
    g_home = g_lam.sum()
    g_rho = np.sum(w * dtau_dr / tau) if use_rho else 0.0

    # El ultimo ataque no es libre: vale menos la suma de los demas. Mover
    # att_free[i] mueve tambien a attack[n-1] en sentido contrario, y esa
    # segunda mitad de la derivada es lo que se resta aqui.
    g_att_free = g_att[:n_teams - 1] - g_att[n_teams - 1]

    grad = -np.concatenate([g_att_free, g_def, [g_home], [g_rho]])
    return nll, grad


def time_weights(match_dates, cutoff, xi):
    """Peso de cada partido segun su antiguedad: exp(-xi * dias).

    Con xi = 0 todos los partidos pesan igual (Poisson clasico). Con
    xi = 0.002, un partido de hace un ano pesa ~48% de uno de hoy, y uno de
    hace tres anos pesa ~11%. Es lo que permite que el modelo se entere de que
    un equipo cambio de entrenador, de plantilla o de nivel.
    """
    if xi <= 0:
        return np.ones(len(match_dates))
    days = np.array([(cutoff - d).days for d in match_dates], dtype=float)
    return np.exp(-xi * days)


def fit(matches, cutoff, xi=0.0, use_rho=True, reg=0.0,
        warm_start=None, max_iter=500):
    """Ajusta el modelo con los partidos dados.

    `matches` debe traer SOLO partidos anteriores a `cutoff`. Esa es la regla 4
    y quien llama es responsable de respetarla; aqui se verifica y se falla
    fuerte si se viola, porque un leakage silencioso es peor que un error.
    """
    dates = [m["date"] for m in matches]
    if dates and max(dates) >= cutoff:
        raise ValueError(
            f"DATA LEAKAGE: hay partidos con fecha {max(dates)} >= corte {cutoff}")

    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    hi = np.array([idx[m["home"]] for m in matches])
    ai = np.array([idx[m["away"]] for m in matches])
    x = np.array([m["hg"] for m in matches], dtype=float)
    y = np.array([m["ag"] for m in matches], dtype=float)
    w = time_weights(dates, cutoff, xi)

    # Punto de partida: todo el mundo promedio, localia en un valor tipico,
    # rho en 0. Si venimos de un ajuste anterior (warm start) se reutilizan sus
    # parametros para los equipos conocidos: acelera mucho el backtest, porque
    # de una semana a la otra la liga casi no cambia.
    p0 = np.zeros(2 * n + 1)
    p0[2 * n - 1] = 0.25
    if warm_start is not None:
        for t, i in idx.items():
            if warm_start.knows(t):
                j = warm_start.index[t]
                if i < n - 1:
                    p0[i] = warm_start.attack[j]
                p0[n - 1 + i] = warm_start.defense[j]
        p0[2 * n - 1] = warm_start.home_adv
        p0[2 * n] = warm_start.rho if use_rho else 0.0

    bounds = [(-3, 3)] * (n - 1) + [(-3, 3)] * n + [(-1, 1)]
    bounds.append(RHO_BOUNDS if use_rho else (0.0, 0.0))

    res = minimize(
        _neg_log_likelihood, p0,
        args=(n, hi, ai, x, y, w, use_rho, reg),
        jac=True,                       # la funcion devuelve (valor, gradiente)
        method="L-BFGS-B", bounds=bounds,
        # Con decaimiento fuerte el ajuste necesita ~230 iteraciones. Con el
        # gradiente analitico cada una cuesta una sola evaluacion, asi que un
        # tope holgado no cuesta nada y evita reportar ajustes a medio hacer.
        options={"maxiter": max_iter, "maxfun": 50 * max_iter},
    )

    attack, defense, home_adv, rho = _unpack(res.x, n)
    fitted = DixonColesFit(teams, attack, defense, home_adv,
                           rho if use_rho else 0.0, xi,
                           len(matches), cutoff, bool(res.success))
    fitted.reg = reg
    # Peso efectivo por equipo: cuantos "partidos equivalentes" sostienen cada
    # par de parametros. Es el numero que explica por que un ascendido produce
    # predicciones extremas, y la F4 lo va a necesitar para diagnosticar.
    eff = np.bincount(hi, w, n) + np.bincount(ai, w, n)
    fitted.effective_weight = {t_: float(eff[i]) for t_, i in idx.items()}
    return fitted
