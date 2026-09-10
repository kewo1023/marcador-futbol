# Qué aprendí construyendo esto

*[English version](LEARNINGS.md)*

Un modelo de pronóstico de fútbol que se autoevalúa: registra sus predicciones
antes de que se jueguen los partidos, ingiere los resultados, se mide contra el
mercado y decide solo si cambiar de modelo.

Este documento es el resumen honesto de qué funcionó y qué no. La segunda parte
es más larga que la primera, y eso no es un accidente del proyecto: es lo que
pasa cuando uno mide de verdad.

---

## La tesis: el sistema de medición se construye antes que el modelo

El instinto es abrir un notebook, entrenar un clasificador de gana/empata/pierde
y mirar la accuracy. Sale 52% y no hay forma de saber si eso es bueno, malo o
suerte.

Aquí las dos primeras fases no produjeron ningún modelo. Produjeron un
**marcador**: una tabla de predicciones inmutables, resultados ingeridos, y tres
métricas. El primer "modelo" evaluado fue deliberadamente tonto — la frecuencia
histórica base.

**La tesis se sostuvo, y de una forma que no esperaba.** Al medir los baselines
antes de modelar nada, apareció esto:

| Referencia | log-loss |
|---|---|
| Frecuencia base | 1.0679 |
| Elo (un rating de 20 líneas) | 0.9845 |
| Mercado (cierre, sin margen) | 0.9556 |

Todo el espacio disponible eran 0.112 de log-loss, y Elo ya se comía el 74%.
Saber eso **antes** de escribir el modelo cambió la expectativa entera: la vara
no era la frecuencia base, era Elo, y lo que quedaba por ganar eran 0.029.

Sin esa medición previa, habría celebrado ganarle a la frecuencia base — que es
trivial — durante semanas.

---

## Lo que funcionó

**El decaimiento temporal es casi toda la ganancia.** Un Poisson que trata igual
un partido de 2015 y uno de la semana pasada saca 1.0086: es *peor* que Elo. Lo
que vuelve competitivo al modelo no es la estructura de goles, es olvidar. El
aporte medido: −0.0257 de log-loss, concluyente.

**La regularización, que no estaba en el plan.** El modelo emitía
probabilidades de hasta **0.74%** a resultados que después ocurrían, y log-loss
cobra esos casos carísimo. La causa: los equipos recién ascendidos tienen peso
efectivo casi nulo bajo decaimiento temporal, así que sus parámetros se
estimaban sobre nada. Empujarlos hacia el promedio de la liga subió la
probabilidad mínima emitida a 4.52% y mejoró −0.0040 (p = 0.034).

**Escribir el motor a mano.** Diagnosticar lo anterior exigió entrar a la
función de verosimilitud y agregarle un término. Con una librería cerrada no
habría sido posible. Y en la fase de mercados nuevos, apuntar el mismo motor a
otra columna costó horas en vez de semanas.

**El gate de promoción.** El candidato solo reemplaza al modelo en producción si
gana en validación out-of-time *y* la diferencia sobrevive un bootstrap pareado.
El primer desafío real fue un rechazo: una configuración que ganaba en el bloque
de afinado y perdía en el del gate. Sobreajuste, atrapado donde debía.

---

## Lo que no funcionó

**`rho`, la mitad del nombre del modelo.** Dixon-Coles corrige la correlación
entre marcadores bajos (0-0, 1-0, 1-1). Aporte medido: **−0.0002, p = 0.62.**
Nada. El paper original es de 1997 sobre datos ingleses de 1992-95; esa
dependencia no aparece en la Premier de 2015-2026. Se dejó implementado y
desactivable, no borrado, para poder re-medirlo en otra liga.

**El árbitro en el mercado de tarjetas.** El plan lo daba por decisivo, y el
rango entre árbitros es real y grande: 3.98 amarillas por partido el más
tarjetero contra 2.63 el que menos, sobre una media de 3.47. Pero **no
predice**: el historial de un árbitro correlaciona **+0.0245** con las tarjetas
del partido que va a pitar, contra +0.196 del modelo de equipos. Confiar del
todo en él empeora el log-loss en 0.0509.

Es la lección más útil del proyecto: *"es obvio que el árbitro influye"* es
cierto y aun así habría empeorado el modelo. Influye en el pasado; no se
proyecta.

**El modelo crudo en corners.** Perdía contra decir "el promedio de la liga" en
las cuatro líneas. La señal existe (correlación 0.119 entre total predicho y
real, comparable a la de goles) pero es débil frente al ruido: el modelo varía
con desviación 0.93 cuando la realidad varía 3.39.

**Poisson para corners y tiros.** Poisson exige varianza = media. Se cumple en
goles (dispersión residual 0.86), amarillas (0.86) y tiros a puerta (0.99). No
se cumple en corners (1.34) ni en tiros totales (1.46).

**Cualquier intento de convertir el modelo en dinero.** Apostando 1 unidad
plana cuando el modelo ve valor esperado positivo, sobre 2127 apuestas: ROI
**−8.50%**, con el intervalo entero por debajo de cero. Peor que apostar a todos
los partidos a ciegas (−6.03%).

El filtro de valor no es neutro, es **activamente dañino**: selecciona los
partidos donde el modelo más discrepa del precio, que son justo donde el mercado
tiene razón. Subir el umbral de EV empeora el resultado hasta −16.55%. Y el
movimiento de la línea lo confirma por otra vía: CLV medio −1.31%, el mercado se
aleja de las selecciones entre tomar el precio y el cierre.

Era lo que anticipaba el log-loss, y por eso se midió con la expectativa escrita
antes de mirar: un modelo peor que el mercado no puede batir al mercado.

**Los tres intentos de cerrar la brecha en victorias locales.** El diagnóstico
señaló ese frente; se atacó con tres ideas y el gate rechazó las tres.

Una ventaja de local por equipo resultó ser **ruido puro**: la variación entre
equipos (6.71%) es la que produciría el azar (6.06%). Mezclar la fuerza estimada
con tiros a puerta **desplazaba el nivel en vez de discriminar** — la
probabilidad de local subía al 48.7% y la de empate se hundía al 15.9% cuando la
real es 22.5%, con la correlación intacta. Y una capa de recalibración con forma
reciente sí aportó discriminación real (correlación con victoria local 0.3377 →
0.3502, sobreviviendo a que se le quitara la capacidad de mover el nivel) pero
solo **−0.0026** de log-loss, indistinguible del ruido sobre 790 partidos.

**Tres de los cuatro mercados nuevos.** De goles over/under, corners, tarjetas y
tiros a puerta, solo **tarjetas** le gana a la frecuencia base de forma
concluyente (p = 0.038 / 0.000 / 0.029). Los otros tres dan mejoras positivas
pero indistinguibles del ruido sobre 760 partidos.

---

## Errores que cometí, y cómo se detectaron

Esta sección existe porque es la parte que más dice sobre cómo trabajo.

**Declaré una victoria que no existía.** La primera versión del backtest
imprimía *"LE GANA a Elo por 0.0018"*. El intervalo de confianza cruzaba cero de
lado a lado (p = 0.55). Lo que lo detectó fue correr un bootstrap pareado en vez
de comparar promedios. **La corrección no fue borrar la frase: fue meter la
prueba de significancia dentro del script**, para que no pudiera volver a pasar.
Ese mismo mecanismo es hoy el gate de promoción.

**Inventé una causa en vez de investigarla.** Al no encontrar partidos de
Premier en el archivo de próximos partidos, escribí que era por un parón de
selecciones. Nunca lo verifiqué; era falso, y quedó escrito en cinco archivos.
La razón real es que ese archivo cubre una ventana de ~3 días y la jornada caía
fuera. Había 18 partidos de otras seis ligas en el mismo archivo — el dato que
lo desmentía estaba a la vista.

Lo grave no fue el dato: la explicación inventada **hacía que mi propio código
pareciera correcto**, y por eso me impidió hacer la pregunta que había debajo —
si una ventana de 3 días alcanza para predecir todo antes del kickoff. De ahí
salió el detector de partidos jugados sin predicción, que hoy pone el workflow
en rojo cuando hay un hueco.

**Un número imposible.** Al medir la sobredispersión, condicionar por el modelo
dio una varianza *mayor* que la bruta. Eso no puede pasar: explicar parte de la
variación no puede aumentarla. El error era mío (ajusté con decaimiento temporal
y evalué contra once años de partidos). Lo que lo delató no fue que se viera
raro, fue que **el número no podía ser cierto**.

**Ediciones que fallaron en silencio.** Varias ediciones automatizadas de
archivos no se aplicaron porque el texto buscado no llevaba tildes y el archivo
sí. Una dejó el esquema de la base sin dos columnas: funcionaba en local por una
migración manual, pero **un clon nuevo habría fallado al ingerir**. Se detectó
creando una base desde cero, que es lo que hace el runner de CI en cada corrida.

**Casi acepté un precio que no existía.** El primer análisis de valor usaba la
mejor cuota entre todas las casas y daba 0.67% de margen — demasiado bueno. El
**28.6% de los partidos tenía margen negativo**, o sea arbitraje puro. Un
arbitraje real dura segundos; que apareciera en uno de cada tres partidos
delataba que ese "precio" no era un conjunto simultáneo, sino el máximo de cada
resultado a lo largo de todo el pre-partido. Se reportan los dos escenarios: el
modelo pierde incluso con precios imposibles, y eso hace la conclusión más
firme, no más débil.

**Cortes de datos definidos por índice.** El bloque de prueba estaba escrito
como `SEASONS[6:]`. Al agregar una temporada nueva pasó de 5 a 6 temporadas sin
que nada avisara, moviendo números ya reportados. Ahora van explícitos.

---

## Y cómo se resolvió: cinco ligas

El límite se resolvió de la única forma posible — más datos. Pasar de la
Premier sola a las cinco grandes multiplicó la base por cinco:

| | Una liga | Cinco ligas |
|---|---|---|
| Partidos | 4.210 | 19.909 |
| Bloque del gate | 790 | 3.650 |
| Diferencia mínima detectable | 0.0060 | **0.0022** |

Cada liga se ajusta por separado; lo que se junta son las pérdidas por partido.

**La capa de recalibración, rechazada con una liga, pasó el gate con cinco:**
−0.0033, IC [−0.0054, −0.0011], p = 0.003. Mejora en cuatro de las cinco, lo
que descarta el artefacto de una sola competición. Es la primera promoción del
proyecto, después de tres rechazos.

Con una ironía que vale registrar: **la excepción es la Premier** (+0.0005),
que es justo donde se descubrió la hipótesis. Una pista encontrada mirando una
competición valió para las otras cuatro y no para ella. Es un recordatorio de
que un hallazgo confirmado en el mismo sitio donde se encontró no está
confirmado.

## El límite que encontré al final

El gate rechazó la capa de recalibración, y al preguntarle por qué salió el
hallazgo más útil de todo el proyecto:

**Con 790 partidos, el gate solo puede declarar concluyente una diferencia de
0.0060 o mayor.** Validar la mejora medida (−0.0026) exigiría ~4.279 partidos:
once temporadas de una sola liga.

La distancia total del modelo al mercado es 0.0230. O sea que **solo son
demostrables las mejoras que cierren más de una cuarta parte de esa distancia de
una vez**. Todo avance incremental es invisible, y no porque el gate esté mal
—su conservadurismo es exactamente lo que impide que el sistema se degrade—
sino porque una liga no da suficientes partidos.

Eso cambia cuál es el siguiente paso. No es un modelo mejor: son **más datos**.
Cuatro ligas grandes más multiplicarían por cinco el bloque del gate y pondrían
estas mejoras dentro de lo verificable. Cambiar de liga es una constante en
`config.py` — la decisión de la F0 de empezar por una sola liga fue correcta
para arrancar, y este es el punto donde deja de serlo.

## Dónde queda el proyecto

| | log-loss | Contra Elo |
|---|---|---|
| Frecuencia base | 1.0679 | — |
| Elo | 0.9845 | — |
| **Modelo final** | **0.9786** | −0.0059, **p = 0.147** |
| Mercado | 0.9556 | — |

**Contra Elo es un empate con ventaja, no una victoria.** El modelo queda por
delante, pero el intervalo cruza cero sobre 1900 partidos. Contra el mercado
pierde por 0.0230, y eso sí es concluyente.

El diagnóstico automático dice dónde se pierde: el modelo **le gana al mercado**
en victorias visitantes (−0.0203) y en partidos con tarjeta roja (−0.0116), y
devuelve todo en **victorias locales** (+0.0386). Ese es el frente abierto.

### Limitaciones que hay que decir

- **Una sola liga.** Nada aquí demuestra que el enfoque se traslade a otra.
- **Corners, tarjetas y tiros se miden sin techo.** La fuente no publica cuotas
  para esos mercados, así que solo se sabe si el modelo aporta algo, no cuánto
  le falta para lo alcanzable. Es una medición más débil que la de goles.
- **F7 se midió sobre backtest, no sobre apuestas reales.** Nadie apostó un
  peso: es una simulación con los precios históricos que publica la fuente.
- **El track record en vivo todavía no existe.** El sistema está construido y
  verificado de punta a punta con el reloj retrocedido sobre datos reales, pero
  no ha emitido aún su primer lote de predicciones sobre partidos futuros. Hasta
  que lo haga y acumule ~100 partidos, todo lo de arriba es backtest.

---

## Qué haría distinto

**Empezaría por el bootstrap pareado, no por el promedio.** Casi todas las
decisiones del proyecto se tomaron comparando dos números, y la mitad de esas
comparaciones no significaban nada. Tener la prueba de significancia desde el
primer día habría ahorrado dos conclusiones falsas.

**Verificaría los baselines antes de elegir el modelo.** Saber que Elo cubría el
74% del espacio disponible cambió qué contaba como éxito. Ese número tardó dos
fases en aparecer y debería haber sido lo primero.

**Trataría cada resultado sorprendente como un bug propio hasta demostrar lo
contrario.** Las tres veces que algo salió raro —el modelo perdiendo en corners,
la dispersión imposible, la ausencia de partidos— la respuesta correcta fue
medir, no explicar. Las dos veces que expliqué primero, me equivoqué.
