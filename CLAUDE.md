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

## Regla 6 — Ninguna comparación se decide por el promedio

Dos modelos pueden separarse por 0.002 de log-loss y que eso no signifique nada:
con unos miles de partidos, esa diferencia cabe holgada dentro de la variación
que produce el azar.

**Toda comparación entre modelos pasa por un bootstrap pareado**, y el intervalo
de confianza manda sobre la media. Si el intervalo contiene cero, no hay
diferencia demostrada — aunque la media diga lo contrario.

De dónde sale: una versión temprana de este proyecto anunció que el modelo "le
ganaba a Elo por 0.0018" con un intervalo que cruzaba cero de lado a lado. La
corrección no fue borrar la frase, fue meter la prueba dentro del script para
que no pudiera repetirse. Ese mismo mecanismo es hoy el gate de promoción.

**Corolario sobre la potencia:** cuando el gate rechaza, hay que preguntarle si
podía haber detectado la diferencia. Un rechazo por falta de potencia no dice
que el candidato no sirva; dice que con esos datos no se puede demostrar que
sirva. Distinguir los dos casos es lo que llevó de una liga a cinco.

## Regla 7 — El guardia de pre-commit no ve dentro de los binarios

El hook lee las líneas agregadas del diff de texto. Un PDF, una imagen o una
hoja de cálculo solo producen «Binary files differ», así que **su contenido no
se revisa**.

Todo binario que entre al repositorio se revisa a mano —extrayendo su texto—
antes del primer commit. Y si un dato protegido tiene que aparecer dentro del
binario, **no se escribe en el código fuente que lo genera**: se deriva en
tiempo de ejecución. El generador del tutorial lee la URL del repositorio con
`git remote get-url origin` por esa razón exacta.

## Regla 8 — Solo el runner escribe en el ledger real

La misma configuración da probabilidades distintas en una máquina local y en el
runner de GitHub Actions a partir del sexto decimal (scipy sobre distinta
arquitectura). Como `append_predictions` rechaza cualquier probabilidad que no
coincida con la ya escrita, correr `04_predict.py` sin `--dry-run` en local
contra `ledger/` termina en «INMUTABILIDAD VIOLADA» — o peor, si el ledger
local estuviera vacío, escribiría predicciones que el runner después rechazaría.

En local, `04_predict.py` y `05_score.py` se corren **siempre** con `--dry-run`
o contra un ledger de prueba. El único que escribe en `ledger/` es el workflow.

### Cómo probar sin tocar el ledger

`MARCADOR_LEDGER_DIR` apunta los scripts y el dashboard a otro directorio. El
patrón que se usó para probar cada mercado nuevo en vivo:

1. Respaldar `data/marcador.sqlite` (los scripts escriben en la base local; las
   predicciones insertadas ahí son inmutables por trigger y no se pueden borrar).
2. Copiar el ledger real a un directorio de prueba, quitando `predictions.csv`.
3. Generar predicciones ficticias para partidos **ya jugados** (con el motor
   real para los mercados over/under, aleatorias para el 1X2), escribirlas en
   el `predictions.csv` de prueba.
4. Correr `05_score.py` con `MARCADOR_LEDGER_DIR` apuntando ahí: busca los
   resultados en la base, escribe `results.csv` y `metrics.csv` de prueba.
5. Levantar el dashboard con la misma variable y mirarlo.
6. Restaurar la base desde el respaldo.

Es la única forma de ver el camino completo predicción → resultado → marcador →
dashboard sin esperar una jornada real ni contaminar el ledger.

## Regla 9 — Un push que añade un módulo exige reboot en Streamlit Cloud

Streamlit Cloud redespliega en cada push sin reiniciar el proceso de Python.
Un módulo nuevo en `src/`, o un cambio en lo que un módulo exporta, se rompe
con `ImportError` —o deja secciones en blanco— hasta hacer **Reboot app**. El
dashboard infiere lo que puede desde el ledger para no quedarse en blanco, pero
el reboot lo tiene que hacer una persona.

## Convenciones de código

- Python 3.13, librería estándar donde alcance. Sin dependencias que no se usen.
- SQLite como única base de datos. Un archivo, sin servidor.
- Los scripts de `scripts/` se numeran por orden de ejecución y son idempotentes:
  correrlos dos veces no duplica ni corrompe nada.
- Comentarios en español, nombres de variables y de tablas en inglés.
