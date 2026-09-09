# marcador-futbol

Sistema de pronóstico de fútbol que se autoevalúa: registra sus predicciones
antes de que se jueguen los partidos, ingiere los resultados, se mide contra sí
mismo y contra el mercado, y solo promueve un modelo nuevo cuando gana.

**La tesis:** el sistema que juzga al modelo se construye antes que el modelo.
Un modelo que "se corrige solo" necesita saber en qué dirección corregirse, y
eso solo lo da un sistema de medición que ya existía.

## Estado

| Fase | Qué es | Estado |
|------|--------|--------|
| F0 | Fundaciones y alcance | ✅ |
| F1 | Datos y el marcador | ✅ |
| F2 | Motor Dixon-Coles | ✅ |
| F3 | Loop automatizado (GitHub Actions + dashboard) | ✅ |
| F4 | Reentreno con gate de promoción | ✅ |
| F5 | Mercados nuevos: corners, tarjetas, tiros | ✅ |
| F6 | Empaquetado y documentación | ⬜ |

## El marcador hoy

Backtest walk-forward sobre Premier League. Las 11 temporadas se parten en
3 de calentamiento, 3 de validación (donde se eligen los hiperparámetros) y
**5 de prueba, que son las únicas que se reportan**. Elegir `xi` mirando las
mismas temporadas que luego se reportan sería leakage: no entra por las
features, entra por la decisión de qué hiperparámetro usar.

| Modelo | log-loss ↓ | Brier ↓ | accuracy | % del espacio cubierto |
|---|---|---|---|---|
| Frecuencia base | 1.0679 | 0.6461 | 44.2% | — (es el piso) |
| Poisson simple | 1.0086 | 0.6021 | 50.7% | 52.8% |
| Elo | 0.9845 | 0.5871 | 54.3% | 74.3% |
| Poisson + decaimiento | 0.9829 | 0.5838 | 53.3% | 75.7% |
| Dixon-Coles (+ rho) | 0.9826 | 0.5837 | 53.3% | 75.9% |
| **Dixon-Coles + regularización** | **0.9786** | **0.5823** | 53.2% | **79.5%** |
| Mercado (cierre, sin margen) | 0.9556 | 0.5670 | 55.9% | — (es el techo) |

`accuracy` se muestra como contexto y no decide nada — ver la regla 5 de
[CLAUDE.md](CLAUDE.md). Nótese que el modelo final tiene *menos* accuracy que
Elo y aun así es mejor: es exactamente el caso que la regla 5 anticipa.

### Qué aportó cada pieza

Comparación pareada sobre los mismos partidos, con bootstrap de 20.000
remuestreos. Negativo = mejora.

| Cambio | Diferencia | IC 95% | ¿Concluyente? |
|---|---|---|---|
| Decaimiento temporal | −0.0257 | [−0.0355, −0.0156] | **sí** |
| Corrección `rho` de marcadores bajos | −0.0002 | [−0.0012, +0.0007] | no |
| Regularización | −0.0040 | [−0.0093, −0.0002] | **sí** |
| Modelo final − Elo | −0.0059 | [−0.0137, +0.0020] | no |
| Modelo final − mercado | +0.0230 | [+0.0151, +0.0309] | **sí** (el mercado gana) |

**Tres cosas que vale la pena leer de esa tabla.**

**El decaimiento temporal es toda la ganancia.** Un Poisson que trata igual un
partido de 2015 y uno de la semana pasada es *peor* que Elo. Lo que lo vuelve
competitivo no es la estructura de goles: es olvidar. El valor elegido en
validación, `xi = 0.002`, equivale a una vida media de unos 11 meses.

**`rho` no aporta nada.** La corrección de marcadores bajos es la mitad del
nombre "Dixon-Coles" y aquí es peso muerto: −0.0002 con p = 0.62, y el
parámetro ajustado se queda en −0.004 cuando el paper original reportaba
valores cerca de −0.13. El paper es de 1997 y usó datos ingleses de 1992-95;
la dependencia entre marcadores bajos que existía entonces no aparece en la
Premier de 2015-2026. Se deja implementado y desactivable para poder
re-medirlo en otra liga o en otro mercado.

**Contra Elo es un empate con ventaja, no una victoria.** El modelo final
queda 0.0059 por delante, pero el intervalo cruza cero (p = 0.147). Sobre
1730 partidos eso no alcanza para declararlo mejor, y el script lo dice así en
vez de anunciar un triunfo.

### Por qué hizo falta la regularización

El diagnóstico por tipo de resultado mostró que Dixon-Coles le gana a Elo en
victorias locales y visitantes, y devuelve toda la ganancia en los empates.
Pero el daño grueso venía de otro lado: el modelo emitía probabilidades
extremas —hasta **0.74%**— a resultados que después ocurrían, y log-loss cobra
esos casos carísimo. La causa eran los equipos recién ascendidos: con
decaimiento temporal su peso efectivo es casi cero, así que sus parámetros se
estimaban sobre nada y se iban al extremo.

La regularización empuja hacia el promedio de la liga a los equipos de los que
hay pocos datos, y deja quietos a los que tienen muchos. La probabilidad
mínima emitida pasó de 0.74% a **4.52%**.

## Cuatro mercados sobre un motor

Cambiar de mercado es cambiar de qué columna salen los dos conteos. El motor no
sabe si cuenta goles, corners, tarjetas o tiros. Esa era la razón para escribir
Dixon-Coles a mano en la F2, y aquí se cobra.

Se cobra **con dos matices que solo aparecen al medirlo.**

### Matiz 1: Poisson no basta en todos lados

Poisson exige varianza = media. Medida la dispersión residual sobre 790
partidos, ya descontada la fuerza de los equipos:

| Evento | Dispersión residual | ¿Poisson? |
|---|---|---|
| Goles | 0.86 | Sí |
| Amarillas | 0.86 | Sí |
| Tiros a puerta | 0.99 | Sí |
| **Corners** | **1.34** | No |
| **Tiros totales** | **1.46** | No |

En los dos últimos la realidad se abre más de lo que Poisson representa, y un
Poisson daría probabilidades demasiado seguras cerca de la media y demasiado
flacas en las colas — justo donde viven los over/under. No hizo falta otro
modelo: la media la sigue estimando el mismo motor y solo la distribución
predictiva pasa a binomial negativa, con la dispersión estimada de los
residuos. Un parámetro, no un rediseño.

### Matiz 2: el modelo crudo pierde contra la frecuencia base en corners

La señal existe —correlación 0.119 entre el total predicho y el real,
comparable a la de goles (0.137)— pero es débil frente al ruido: el modelo
varía con desviación 0.93 cuando la realidad varía 3.39. La confianza de más
cuesta más de lo que aporta la señal.

Se corrige encogiendo hacia la base: `p = w·modelo + (1−w)·base`, con `w`
elegido por mercado en el bloque de afinado. El valor que sale **mide cuánto se
le puede creer al modelo en ese mercado**, y reproduce por una vía
independiente el orden de la señal:

| Mercado | Correlación | `w*` |
|---|---|---|
| Tarjetas | 0.196 | 0.8–0.9 |
| Tiros a puerta | 0.163 | 0.6–0.7 |
| Goles | 0.137 | 0.5–0.8 |
| Corners | 0.119 | 0.4–0.6 |

### El resultado, sin adornos

Temporadas 2024/25–2025/26, con `w` elegido en 2021/22–2023/24:

| Mercado | ¿Le gana a la frecuencia base? | p |
|---|---|---|
| **Tarjetas 2.5 / 3.5 / 4.5** | **Sí, las tres** | 0.038 / 0.000 / 0.029 |
| Corners (4 líneas) | Positivo, no concluyente | 0.12 – 0.94 |
| Goles over/under (3 líneas) | Positivo, no concluyente | 0.39 – 0.59 |
| Tiros a puerta (3 líneas) | Positivo, no concluyente | 0.16 – 0.76 |

**De cuatro mercados, uno funciona de forma demostrable.** Las tarjetas, que
son justo el mercado que el plan original daba por más difícil.

### Sobre el árbitro, que el plan daba por decisivo

El plan decía que las tarjetas dependerían del árbitro tanto como de los
equipos. El rango entre árbitros es real y grande: 3.98 amarillas por partido
el más tarjetero contra 2.63 el que menos, sobre una media de 3.47.

**No sirve para predecir.** El historial de un árbitro correlaciona +0.0245 con
las tarjetas del partido que va a pitar, contra +0.196 del modelo de equipos.
Confiar del todo en él empeora el log-loss en 0.0509, y el mejor ajuste posible
es el que casi lo ignora. El motor tiene la puerta abierta (`context_scale`)
por si aparece una covariable de partido que sí prediga, pero esta no lo hace.

### El techo, donde lo hay

La fuente publica cuotas de cierre para 1X2 y para over/under 2.5 goles, y para
nada más. Corners, tarjetas y tiros se miden **solo contra la frecuencia
base**: se sabe si el modelo aporta, no cuánto le falta para lo alcanzable. Es
una medición más débil y no hay que tratarla como si fuera equivalente.

## El gate de promoción

**La regla, en una línea: el campeón conserva el título salvo que lo derroten
de forma concluyente. Un empate lo gana el campeón.**

Cada lunes se busca una configuración nueva en un bloque de afinado, y se la
enfrenta al campeón sobre tres temporadas que **ninguna de las dos vio**. Los
dos se reajustan con el mismo procedimiento: comparar al campeón tal como está
contra un retador recién entrenado haría ganar siempre al retador por tener
parámetros más frescos, y el gate no estaría midiendo lo que cree medir.

La decisión no se toma comparando promedios, sino con un bootstrap pareado. La
razón está documentada en la propia F2 de este repo: allí el proyecto declaró
que el modelo "le ganaba a Elo por 0.0018" y resultó ser ruido. Si el gate
comparara promedios, promovería cada vez que el azar diera una décima de
ventaja — y como promover es acumulativo, el sistema se degradaría a punta de
mejoras imaginarias. Que es exactamente lo que esta fase existe para impedir.

El primer desafío real quedó registrado y fue un **rechazo**: el retador
(`reg=0.005`) ganaba en el bloque de afinado y perdió en el del gate. Sobreajuste
al bloque de búsqueda, atrapado donde debía.

El modelo en producción vive en `ledger/champion.json`, **no en el código**. Si
fuera una constante de Python, promover exigiría que una persona editara un
`.py`: el sistema no se estaría corrigiendo solo, estaría pidiendo permiso.
`git log ledger/champion.json` es el historial de qué modelo emitió cada
predicción y desde cuándo.

## Dónde pierde el modelo

`scripts/07_diagnose.py` segmenta el error contra el mercado y escribe
`ledger/diagnostics.csv`. Compara contra el mercado y no contra un número
suelto porque un log-loss alto en un segmento puede ser solo un segmento
difícil; lo que importa es cuánto se pierde donde el mercado enfrenta lo mismo.

Sobre 2024/25–2026/27, la brecha total contra el mercado es +0.0161, y se
reparte así:

| Segmento | Brecha | Aporta |
|---|---|---|
| Gana local | +0.0386 | **+0.0171** |
| Empate | +0.0254 | +0.0064 |
| Gana visitante | −0.0203 | −0.0066 (el modelo **gana**) |
| Con equipo recién ascendido | +0.0100 | +0.0029 |
| Con tarjeta roja | −0.0116 | −0.0013 (el modelo **gana**) |

Dos lecturas que valen: el segmento de recién ascendidos ya casi no duele
—confirma que la regularización de la F2 hizo su trabajo— y el modelo le gana
al mercado en victorias visitantes y en partidos con roja. El frente abierto
son las **victorias locales**, no los empates como parecía en la F2: contra
Elo el problema eran los empates, contra el mercado son los locales.

Esto genera hipótesis, no autoriza cambios. Cualquier idea que salga de aquí
pasa por el gate igual que las demás.

## El loop

Dos workflows de GitHub Actions, a distintas horas y con `concurrency` para que
nunca escriban a la vez:

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `score.yml` | 03:00 UTC diario | Ingiere resultados, los cruza con lo predicho, recalcula el marcador |
| `predict.yml` | 05:00 y 17:00 UTC | Baja los próximos partidos, ajusta el modelo y emite predicciones |
| `retrain.yml` | Lunes 06:00 UTC | Busca un retador, lo pasa por el gate, y diagnostica dónde falla |

Los días sin partidos ninguno de los dos commitea nada.

**La ventana de la fuente es corta y eso condiciona el diseño.** `fixtures.csv`
es el único archivo de próximos partidos que publica football-data.co.uk, y
cubre pocos días: el 2026-09-09 traía 18 partidos de 6 ligas, todos entre el
08/09 y el 10/09. Que una liga no aparezca significa que su siguiente jornada
cae fuera de esa ventana, no que no se juegue.

Eso es **una observación, no una garantía**, así que el sistema no asume que la
ventana alcanza. Después de cada jornada, `05_score.py` comprueba si algún
partido se jugó sin haber sido predicho y lo registra en
`ledger/missed.csv`. Si encuentra alguno, el workflow queda en rojo: un partido
sin predecir es un agujero en el track record, y un agujero silencioso vale
menos que ninguno.

### Dónde viven las predicciones, y por qué importa

En `ledger/`, en texto plano y versionado — no en la base de datos, que está
en `.gitignore` y que además se destruye con el runner de Actions al terminar
el job.

Esa decisión, tomada por una razón de infraestructura, resultó ser la mejor
propiedad del proyecto: **la fecha del commit que agregó una predicción es
prueba externa de cuándo se emitió.** Una columna `created_at` la escribe el
mismo sistema que se está evaluando; el reloj de GitHub, no.

```bash
git log --format="%ad %h" --date=iso -- ledger/predictions.csv
```

Cualquiera puede auditar el track record sin tener que confiar en nosotros. Ver
[ledger/README.md](ledger/README.md).

## Cómo correrlo

Requiere Python 3.11 o superior. La F1 corre solo con la librería estándar.

```bash
python3 scripts/01_ingest.py     # baja los CSV historicos -> data/marcador.sqlite
python3 scripts/02_baseline.py   # genera predicciones baseline y calcula el marcador
```

La F2 necesita scipy, así que corre en un entorno virtual:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python scripts/03_dixon_coles.py   # ajusta, hace backtest y compara
```

El loop y el dashboard:

```bash
./.venv/bin/python scripts/04_predict.py --dry-run   # que predeciría, sin escribir
./.venv/bin/python scripts/05_score.py               # ingiere resultados y mide
./.venv/bin/python scripts/06_retrain.py --dry-run   # que decidiria el gate, sin escribir
./.venv/bin/python scripts/07_diagnose.py            # donde pierde contra el mercado
./.venv/bin/python scripts/08_markets.py             # los cuatro mercados
./.venv/bin/streamlit run dashboard/app.py           # dashboard en localhost:8501
```

El dashboard lee **solo el ledger**, nunca la base local. Si necesitara la base,
nadie de afuera podría reproducir lo que muestra.

La primera corrida baja ~1.6 MB de la fuente y tarda menos de un minuto. Las
siguientes usan la copia en `data/raw/`; con `--force` se vuelve a bajar todo.

### Instalar el guardia de pre-commit

Este repo tiene un hook que impide que datos personales entren al historial. No
está versionado a propósito, así que **un clon nuevo no lo trae**. Ver la regla
1 de [CLAUDE.md](CLAUDE.md) para el porqué.

## Cómo está organizado

```
src/marcador/
  config.py     alcance (liga, temporadas) y URLs de la fuente
  db.py         esquema SQLite; las reglas 3 y 4 son triggers, no documentación
  ingest.py     descarga y carga; idempotente
  scoring.py    log-loss, Brier, accuracy, curva de calibración
  baseline.py   frecuencia base, Elo, y el mercado como referencia
  dixon_coles.py  el motor: Poisson + decaimiento + rho, con gradiente analitico
  ledger.py     lectura y escritura append-only del ledger
  backtest.py   walk-forward y ModelConfig, compartidos por el backtest y el gate
  promotion.py  el gate: campeon, retador, y la decision
  diagnostics.py  segmentacion del error contra el mercado
  markets.py    que mercados existen y con que se mide cada uno
scripts/
  01_ingest.py  baja y carga
  02_baseline.py genera predicciones walk-forward y llena el marcador
  03_dixon_coles.py ajusta xi y reg en validacion, y reporta sobre prueba
  04_predict.py   emite predicciones de los proximos partidos (loop)
  05_score.py     ingiere resultados y recalcula el marcador (loop)
  06_retrain.py   busca retador y lo pasa por el gate (semanal)
  07_diagnose.py  donde pierde el campeon contra el mercado
  08_markets.py   backtest de corners, tarjetas y tiros
dashboard/
  app.py          Streamlit; lee solo el ledger
ledger/           predicciones, resultados y metricas — esto SI se versiona
.github/workflows/  los dos cron jobs
```

`data/` no se versiona: la fuente permite usar los datos, no republicarlos.
Este repo publica predicciones y métricas derivadas, nunca el volcado de datos.

## Una nota sobre el techo

La referencia de mercado era la cuota de cierre de **Pinnacle**. La fuente dejó
de publicarla el **17/01/2026**: falta en 170 partidos de 2025/26 y en toda la
temporada 2026/27. Seguir con ella habría dejado al track record en vivo sin
techo contra el cual medirse.

Ahora se usa el **promedio de cierre de todas las casas**, que cubre el 100% de
los partidos desde 2019/20 (y Pinnacle antes, donde el promedio no existe). Es
además una referencia mejor conceptualmente: el consenso del mercado en vez de
la opinión de una casa. Pero es un techo algo más bajo — Pinnacle es la casa
más afilada — y por eso los porcentajes de "espacio cubierto" de esta tabla son
más altos que los que reportaba el README antes de la F4. El baseline viejo
(`market-close-v1`) se conserva intacto en la base y el nuevo se registra como
`market-avgclose-v1`: dos referencias distintas no comparten nombre.

## Fuente de datos

[football-data.co.uk](https://football-data.co.uk) — CSV por temporada y liga,
gratuitos. Traen resultado, corners, tarjetas, tiros, tiros a puerta, árbitro y
cuotas de varias casas incluyendo las de cierre.

Dos cosas que cuestan tiempo si uno no las sabe, y que ya están resueltas en el
código:

- El subdominio `www.` responde **503** a peticiones programáticas. El dominio
  pelado responde 200.
- El formato de fecha cambia entre temporadas: unas traen `dd/mm/yyyy` y otras
  `dd/mm/yy`. La columna `Time` solo existe desde 2019/20.

## Licencia

MIT para el código. Los datos son de sus respectivas fuentes y no se
redistribuyen aquí.
