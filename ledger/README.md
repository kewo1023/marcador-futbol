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
| `results.csv` | El marcador de los partidos que se predijeron | Solo se completa; un resultado registrado no cambia |
| `metrics.csv` | log-loss, Brier y accuracy por modelo | Sí: son derivadas, se recalculan |
| `missed.csv` | Partidos que se jugaron sin que el sistema los predijera | Solo se agregan |
| `champion.json` | Qué modelo está en producción y desde cuándo | Sí, cuando el gate promueve |
| `challenges.csv` | Cada desafío al campeón, promovido o rechazado | Solo se agregan |
| `diagnostics.csv` | Dónde pierde el campeón contra el mercado, por segmento | Sí, se recalcula |
| `fixtures.csv` | Fecha y hora de cada partido predicho, la última que se supo | Sí: la hora cambia, la predicción no |
| `source_health.csv` | Por corrida y liga, qué traía la fuente de fixtures | Solo se agregan |
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
