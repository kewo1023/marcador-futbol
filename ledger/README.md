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

`results.csv` guarda lo mínimo para poder verificar el marcador sin bajar nada
(equipos, goles, resultado). No lleva cuotas, corners, tiros ni árbitro: no es
una copia de la fuente.

## Cómo verificar una predicción

```bash
git log --format="%ad %h" --date=iso -- ledger/predictions.csv | tail -5
```

La fecha del commit que introdujo una fila es anterior al partido que esa fila
predice. Si no lo fuera, el proyecto estaría roto.
