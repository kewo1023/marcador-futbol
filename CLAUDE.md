# marcador-futbol — reglas del proyecto

Modelo de pronóstico de fútbol que se autoevalúa. La tesis del proyecto:
**el sistema que juzga al modelo se construye antes que el modelo.**

## Regla 1 — Ningún dato personal entra a este repositorio

Se asume que este repo **puede volverse público**. Un repo privado se hace
público con un clic, y ese clic no expone el estado de hoy: expone **todo el
historial**. Borrar un dato en un commit posterior NO lo saca del historial.
Esto es preventivo o no es nada.

No entra a ningún archivo versionado, mensaje de commit, nombre de rama ni
nombre de archivo: nada que identifique al autor, dónde está, su situación
laboral o su disponibilidad, su nivel técnico, su presupuesto, las rutas
absolutas de su máquina, ni enlaces a documentos de sus cuentas personales.

**La pregunta que resuelve cada caso: ¿esto describe el SOFTWARE o describe a
una PERSONA?** Lo primero va al repo. Lo segundo va a `CONTEXTO-LOCAL.md`,
que está en `.gitignore` desde antes del primer commit.

Cuando el software sí necesita el dato, se escribe **la consecuencia, no el
dato**: "hay diferencia de horario entre desarrollo y producción" en vez de
nombrar la zona horaria.

Hay un hook `pre-commit` en `.git/hooks/` que bloquea esto de forma automática.
No está versionado a propósito: un guardia versionado que apunta a una lista
secreta delata qué se protege. **Un clon nuevo no lo trae** — hay que
instalarlo a mano (ver README).

## Regla 2 — Los datos crudos no se redistribuyen

`data/` está en `.gitignore` entero, y también `*.csv`. Las fuentes de datos
deportivos permiten **usar** los datos, no republicarlos. Lo que este repo
publica son **predicciones y métricas derivadas**, nunca el volcado de datos.
Cualquiera que clone el repo baja los datos él mismo con `scripts/01_ingest.py`.

## Regla 3 — Una predicción guardada no se toca nunca más

Es la regla de la que depende todo lo demás. Una predicción se escribe **antes
del kickoff**, con la fecha en que se generó y la versión del modelo que la
generó, y a partir de ahí es de solo lectura. Sin ese registro inmutable,
cualquier evaluación posterior está contaminada y no hay forma de darse cuenta.

Esto no se deja a la disciplina: la base de datos lo impone con triggers que
abortan cualquier `UPDATE` o `DELETE` sobre `predictions`, y cualquier `INSERT`
cuyo `created_at` sea posterior al kickoff.

## Regla 4 — Ninguna feature usa información del futuro

Toda variable de un partido se calcula **únicamente con datos con fecha
anterior al kickoff de ese partido**. Sin excepciones. El síntoma de violar
esto es que todo sale increíble en backtest y se derrumba en vivo.

El backtest es siempre **walk-forward**: entrenar con las temporadas 1 a N,
predecir la N+1. Nunca en desorden, nunca con muestreo aleatorio.

## Regla 5 — Accuracy no decide nada

Las métricas del proyecto son **log-loss** (la que decide si un modelo
reemplaza a otro), **Brier score** y la **curva de calibración**. Accuracy se
reporta como contexto y nunca como criterio.

## Convenciones de código

- Python 3.13, librería estándar donde alcance. Sin dependencias que no se usen.
- SQLite como única base de datos. Un archivo, sin servidor.
- Los scripts de `scripts/` se numeran por orden de ejecución y son idempotentes:
  correrlos dos veces no duplica ni corrompe nada.
- Comentarios en español, nombres de variables y de tablas en inglés.
