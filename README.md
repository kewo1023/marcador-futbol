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
| F4 | Reentreno con gate de promoción | ⬜ |
| F5 | Mercados nuevos: corners, tarjetas, tiros | ⬜ |
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
| Poisson simple | 1.0086 | 0.6021 | 50.7% | 49.0% |
| Elo | 0.9845 | 0.5871 | 54.3% | 68.9% |
| Poisson + decaimiento | 0.9829 | 0.5838 | 53.3% | 70.2% |
| Dixon-Coles (+ rho) | 0.9826 | 0.5837 | 53.3% | 70.4% |
| **Dixon-Coles + regularización** | **0.9786** | **0.5823** | 53.2% | **73.8%** |
| Mercado (cierre, sin margen) | 0.9468 | 0.5608 | 56.4% | — (es el techo) |

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
| Modelo final − mercado | +0.0227 | [+0.0142, +0.0314] | **sí** (el mercado gana) |

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

## El loop

Dos workflows de GitHub Actions, a distintas horas y con `concurrency` para que
nunca escriban a la vez:

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `score.yml` | 03:00 UTC diario | Ingiere resultados, los cruza con lo predicho, recalcula el marcador |
| `predict.yml` | 05:00 y 17:00 UTC | Baja los próximos partidos, ajusta el modelo y emite predicciones |

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
scripts/
  01_ingest.py  baja y carga
  02_baseline.py genera predicciones walk-forward y llena el marcador
  03_dixon_coles.py ajusta xi y reg en validacion, y reporta sobre prueba
  04_predict.py   emite predicciones de los proximos partidos (loop)
  05_score.py     ingiere resultados y recalcula el marcador (loop)
dashboard/
  app.py          Streamlit; lee solo el ledger
ledger/           predicciones, resultados y metricas — esto SI se versiona
.github/workflows/  los dos cron jobs
```

`data/` no se versiona: la fuente permite usar los datos, no republicarlos.
Este repo publica predicciones y métricas derivadas, nunca el volcado de datos.

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
