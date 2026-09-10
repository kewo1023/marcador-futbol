# Alcance — decisiones de la F0

Documento corto y vinculante. Si algo lo contradice más adelante, se cambia
aquí primero y se deja el porqué.

## Las cinco grandes ligas

**Actualizado el 2026-09-10.** El proyecto empezó con la Premier sola y ahora
corre sobre cinco: Premier League, LaLiga, Bundesliga, Serie A y Ligue 1.
19.909 partidos.

El motivo del cambio no fue querer más cobertura: fue que **el gate se había
quedado ciego**. Con 790 partidos solo podía declarar concluyentes diferencias
de 0.0060 o mayores, y rechazó una mejora real de 0.0026 por falta de potencia.
Con cinco ligas el bloque del gate pasó a 3.650 partidos y su umbral a 0.0022 —
y esa misma mejora pasó.

Cada liga se ajusta por separado; lo que se junta son las pérdidas por partido.
El loop de producción y el gate corren sobre las cinco. Los scripts de análisis
histórico siguen sobre la Premier a propósito: cambiarlos movería números ya
reportados.

## La decisión original: una sola liga, Premier League (`E0`)

*Lo que sigue es el razonamiento de la F0, que se conserva porque fue correcto
para arrancar y explica por qué la Premier sigue siendo la liga primaria.*

Cinco temporadas era el mínimo; se cargan **once** (2015/16 a 2025/26, 4180
partidos) porque el costo de bajar seis más es cero y el modelo de la F2 agradece
el histórico.

**Por qué la Premier y no LaLiga.** Se midieron las dos con los mismos 4180
partidos cada una antes de decidir:

| | Premier | LaLiga |
|---|---|---|
| log-loss del mercado (menor = más predecible) | **0.9524** | 0.9596 |
| Acierto del favorito | 55.1% | 54.4% |
| Empates | 23.7% | **26.0%** |
| Goles por partido | **2.82** | 2.63 |
| Columna `Referee` | **11 de 11 temporadas** | **0 de 11** |

A nivel de partido las dos ligas son prácticamente igual de predecibles, y la
diferencia que hay favorece levemente a la Premier. La creencia de que en la
Premier "cualquiera le gana a cualquiera" describe **el título**, no los
partidos, y la de que LaLiga es predecible describe lo mismo: quién queda
campeón. Este proyecto predice partidos, así que ninguna de las dos creencias
aplica al criterio de selección.

Lo que sí desempata es la última fila. La fuente trae el árbitro en la Premier y
no en LaLiga, y el mercado de tarjetas de la F5 depende del árbitro tanto como
de los equipos. Elegir LaLiga costaría esa fase o una segunda fuente de datos.

Argumentos secundarios en la misma dirección: menos empates (el resultado más
difícil de predecir) y más goles por partido, que le da al modelo Poisson de la
F2 una señal más fuerte por partido.

**Descartado:** LaLiga, por lo del árbitro. Ligas múltiples, porque empezar
ancho es como uno se atora; ampliar después es cambiar una constante en
`config.py`.

## Motor: Dixon-Coles escrito a mano

Un Poisson con dos ajustes: corrige la subestimación de marcadores bajos (0-0,
1-0, 1-1) y pondera los partidos recientes más que los viejos.

Se escribe a mano en vez de usar una librería que lo resuelva en tres líneas.
La librería ahorra unas horas y quita la parte que hace defendible el proyecto:
poder explicar qué hace cada parámetro. Además, el motor escrito a mano es el
que permite apuntar a otra columna en la F5 sin reescribir nada.

**Descartado:** un clasificador de 1X2 entrenado directamente. Predice el
resultado pero no la distribución de marcadores, así que cada mercado nuevo de
la F5 exigiría empezar de cero.

**Actualización tras construirlo (F2).** De los dos ajustes que le dan nombre
al modelo, solo uno sirve en esta liga. El decaimiento temporal aporta casi
toda la mejora; la corrección `rho` de marcadores bajos no aporta nada medible
(−0.0002, p = 0.62). La pieza que sí hizo falta y no estaba en el plan es la
**regularización**: sin ella los equipos recién ascendidos reciben parámetros
extremos y el modelo emite probabilidades de 0.74% a resultados que ocurren.

La decisión de escribirlo a mano se paga aquí: diagnosticar eso y corregirlo
exigió entrar a la función de verosimilitud, que con una librería cerrada no
habría sido posible.

## Mercado inicial: 1X2

Los demás (over/under 2.5, BTTS, corners, tarjetas, tiros) salen de la misma
distribución de marcadores. La tabla `predictions` ya está diseñada para
soportarlos sin migración: una fila por resultado posible, con una columna
`market`.

## Qué NO es este proyecto

- No es un sistema de apuestas. La F7 (comparar contra el mercado) es opcional
  y posterior, y solo tiene sentido si el modelo llega calibrado.
- No redistribuye datos. Ver la regla 2 de `CLAUDE.md`.
