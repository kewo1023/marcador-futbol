# Ledger

Las predicciones del sistema, en texto plano y versionadas.

**Por qué no está en la base de datos.** La base vive en `data/`, que está en
`.gitignore`, y el runner de GitHub Actions se destruye cuando termina el job.
Si las predicciones vivieran solo ahí, cada corrida empezaría en blanco.

**Por qué no se commitea la base entera.** Es un binario (diffs ilegibles) y
lleva el volcado crudo de la fuente, que la regla 2 de `CLAUDE.md` prohíbe
republicar. Aquí solo hay datos derivados: qué predijo el modelo, qué pasó, y
cómo le fue.

**El efecto secundario que vale más que el original.** Al estar versionado, la
fecha del commit que agregó una predicción es prueba externa de cuándo se
emitió. Una columna `created_at` la escribe el mismo sistema que se está
evaluando; el reloj de GitHub, no. Cualquiera puede auditar el proyecto con
`git log ledger/predictions.csv` sin tener que confiar en nosotros.

## Archivos

| Archivo | Qué es | Se reescribe |
|---|---|---|
| `predictions.csv` | Una fila por (partido, modelo, mercado, resultado posible) | **Nunca.** Solo se agregan filas |
| `results.csv` | El marcador de los partidos que se predijeron (`score_source`: quién lo trajo primero) y, cuando football-data.co.uk publica, la cuota de cierre, tarjetas y tiros (`completed_at`) | Solo se completa; un resultado registrado no cambia |
| `metrics.csv` | log-loss, Brier y accuracy por modelo | Sí: son derivadas, se recalculan |
| `missed.csv` | Partidos que se jugaron sin que el sistema los predijera | Solo se agregan |
| `champion.json` | Qué modelo está en producción y desde cuándo | Sí, cuando el gate promueve |
| `challenges.csv` | Cada desafío al campeón, promovido o rechazado | Solo se agregan |
| `diagnostics.csv` | Dónde pierde el campeón contra el mercado, por segmento | Sí, se recalcula |
| `fixtures.csv` | Fecha y hora de cada partido predicho, la última que se supo, y el marcador **provisional** según la fuente de fixtures (`prov_score`, no cuenta) | Sí: la hora cambia, la predicción no |
| `source_health.csv` | Por corrida y liga, qué traía la fuente de fixtures | Solo se agregan |
| `market_pre.csv` | Probabilidad implícita del mercado **antes** del partido (promedio de casas, sin margen), una fila por cada cambio de línea | Solo se agregan |
| `postponed.csv` | Partidos predichos que la fuente movió a otra fecha: id viejo → id nuevo, con la hora vieja y la nueva (hora vieja vacía = la fecha original era provisional). Un aplazamiento **no se evalúa**; una fecha provisional corregida sí, con el resultado del id real | Solo se agregan (una fila por cada cambio de fecha; la última manda) |
| `results_health.csv` | Por corrida y liga, hasta dónde llega la fuente de resultados y cuántos partidos ya jugados le faltan | Solo se agregan |

`results.csv` guarda lo mínimo para poder verificar el marcador sin bajar nada
(equipos, goles, resultado). No lleva cuotas, corners, tiros ni árbitro: no es
una copia de la fuente.

## Cómo verificar una predicción

```bash
git log --format="%ad %h" --date=iso -- ledger/predictions.csv | tail -5
```

La fecha del commit que introdujo una fila es anterior al partido que esa fila
predice. Si no lo fuera, el proyecto estaría roto.

## Por qué el campeón vive aquí y no en el código

Si el modelo en producción fuera una constante de Python, promover exigiría que
una persona editara un `.py` y lo commiteara. El sistema no se estaría
corrigiendo solo: estaría pidiendo permiso.

`git log ledger/champion.json` es el historial completo de qué modelo emitió
cada predicción y desde cuándo.

`challenges.csv` guarda **todos** los desafíos, incluidos los rechazados. Los
rechazos son la evidencia de que el gate hace algo: un historial que solo
muestra promociones es indistinguible de un sistema sin gate.

## Por qué existe `missed.csv`

La fuente publica los próximos partidos en una ventana de pocos días, así que
el loop depende de correr con suficiente frecuencia para agarrar cada partido
mientras está visible. Esa dependencia no se da por buena: después de cada
jornada se comprueba si algún partido se jugó sin haber sido predicho, y si lo
hubo se registra aquí y el workflow queda en rojo.

Se registra en vez de solo avisarse porque un agujero que solo existe en el log
de un job que ya expiró no es un agujero documentado, es uno invisible. Quien
audite el track record tiene que poder ver qué partidos faltan en vez de
suponer que se predijeron todos.

## Por qué existe `postponed.csv`

El `match_id` lleva la fecha del partido. Cuando un partido se aplaza, vuelve
con otro id —el resultado va a llegar con la fecha en que se juegue— y la
predicción emitida para la fecha original queda con el kickoff pasado y sin
resultado nunca. Corregirla no se puede: una predicción no se toca (regla 3).

`04_predict.py` lo detecta con la temporada completa de la fuente de fixtures:
si un partido predicho ya pasó su kickoff, no tiene resultado, y la fuente
trae ese mismo cruce (liga, local, visitante) en otro día, se movió. En una
liga cada cruce se juega una sola vez por temporada, así que no hay nada que
adivinar. Si la fuente lo saca sin fecha nueva, no se concluye nada y sigue
contando como "esperando resultado".

**Aplazamiento: la predicción vieja no se evalúa.** Se predijo con hora
confirmada para un partido que ese día no se jugó, y con información de ese
día. El partido se predice de nuevo con su id nuevo cuando entra en la
ventana, y esa es la que cuenta. Si la fecha nueva ya pasó cuando la fuente la
publica, no hubo predicción válida y el partido queda en `missed.csv`.

**Fecha provisional corregida: la predicción vieja SÍ se evalúa.** Cuando la
liga no ha confirmado la hora, la fuente escribe 00:00, y a veces la fecha
misma es un comodín para toda la jornada. El sistema predice esos partidos
igual: saltarlos habría perdido jornadas enteras (la 5 de la Bundesliga nunca
tuvo hora confirmada antes de jugarse, y uno de sus partidos sí se jugó en la
fecha publicada). Si la fecha resulta otra, la fila de este archivo lleva
`old_kickoff_utc` vacío. Esa predicción es del mismo partido, emitida antes de
jugarse; lo único mal era la fecha. Se evalúa con el resultado del id real si
se cumplen las dos condiciones de `ledger.provisional_aliases`:

- se emitió antes del kickoff real (regla 3, aplicada al partido que sí se
  jugó), y
- el id real no tiene predicción propia. Si la tiene, cuenta esa, que se
  emitió con la fecha correcta y más cerca del partido; contar las dos sería
  contar el mismo partido dos veces.

`05_score.py` busca entonces el resultado del id real, lo guarda en
`results.csv` con su propio id, y lo cruza con la predicción vieja al calcular
el marcador. El id real no se cuenta en `missed.csv`. Mientras la fuente no
corrija la fecha, un partido sin hora cuenta como "esperando resultado" desde
que su fecha termina.

En ningún caso se toca `predictions.csv`. Si un resultado llegara con el id
viejo, el partido sí se jugó en su fecha, y el resultado manda.

El dashboard y `results_health.csv` sacan los partidos movidos de "esperando
resultado", y el dashboard los muestra con su fecha nueva y si se evalúan.
