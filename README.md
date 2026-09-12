# marcador-futbol

*[English version](README.en.md)*

Sistema de pronóstico de fútbol que se autoevalúa: registra sus predicciones
antes de que se jueguen los partidos, ingiere los resultados, se mide contra sí
mismo y contra el mercado, y **decide solo** si cambiar de modelo.

**La tesis:** el sistema que juzga al modelo se construye antes que el modelo.
Un modelo que "se corrige solo" necesita saber en qué dirección corregirse, y
eso solo lo da un sistema de medición que ya existía.

**Cinco ligas:** Premier League, LaLiga, Bundesliga, Serie A y Ligue 1 —
19.909 partidos.

**Dashboard en vivo:** https://marcador-futbol-2rs4efqkkrvipztze7k5mr.streamlit.app/

### Por dónde empezar a leer

| Si quieres… | Ve a |
|---|---|
| Entender el sistema sin leer nada más | **[Tutorial en PDF](docs/TUTORIAL.pdf)** — 9 páginas, diez minutos |
| Saber qué funcionó y qué no, sin adornos | **[APRENDIZAJES.md](APRENDIZAJES.md)** |
| Ver el resultado medido | [El marcador hoy](#el-marcador-hoy), aquí abajo |
| Entender por qué el modelo no puede empeorar solo | [El gate de promoción](#el-gate-de-promoción) |
| Ver el motor | [`src/marcador/dixon_coles.py`](src/marcador/dixon_coles.py) |
| Ver cómo se impide el data leakage | [`src/marcador/db.py`](src/marcador/db.py) — son triggers, no documentación |
| Auditar las predicciones sin confiar en nadie | [`ledger/`](ledger/) y `git log` |

### El resumen en tres líneas

El modelo final saca **0.9786** de log-loss. Elo saca 0.9845 y el mercado
0.9556. Contra Elo queda por delante pero el intervalo de confianza cruza cero
(p = 0.147): **es un empate con ventaja, no una victoria**, y así se reporta.
Contra el mercado pierde, y eso sí es concluyente.

De cuatro mercados construidos sobre el mismo motor, con una liga solo **uno**
le ganaba a su frecuencia base de forma demostrable; con cinco ligas le ganan
**los cuatro**. Tarjetas amarillas, el de mayor ganancia, se emite en vivo.

## Estado

| Fase | Qué es | Estado |
|------|--------|--------|
| F0 | Fundaciones y alcance | ✅ |
| F1 | Datos y el marcador | ✅ |
| F2 | Motor Dixon-Coles | ✅ |
| F3 | Loop automatizado (GitHub Actions + dashboard) | ✅ |
| F4 | Reentreno con gate de promoción | ✅ |
| F5 | Mercados nuevos: corners, tarjetas, tiros | ✅ |
| F6 | Empaquetado y documentación | ✅ |
| F7 | Valor contra el mercado (opcional) | ✅ · sin ventaja |

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

## De una liga a cinco, y la primera promoción

El límite descrito abajo —el gate no podía validar mejoras menores a 0.0060 con
790 partidos— se resolvió de la única forma posible: **más datos**.

| | Una liga | Cinco ligas |
|---|---|---|
| Partidos en la base | 4.210 | **19.909** |
| Bloque del gate | 790 | **3.650** |
| Diferencia mínima detectable | 0.0060 | **0.0022** |

Cada liga se ajusta por separado —los equipos no se solapan, un ajuste conjunto
exigiría efectos de liga— y lo que se junta son **las pérdidas por partido**,
que sí son comparables: un log-loss es un log-loss venga de donde venga.

### El resultado: la capa de recalibración pasó el gate

La misma capa que había sido rechazada con una liga fue sometida de nuevo:

| Liga | n | Campeón | Candidato | Dif. |
|---|---|---|---|---|
| Premier League | 790 | 1.0061 | 1.0066 | +0.0005 |
| LaLiga | 801 | 0.9753 | **0.9686** | −0.0068 |
| Bundesliga | 630 | 0.9997 | **0.9984** | −0.0013 |
| Serie A | 790 | 0.9774 | **0.9723** | −0.0050 |
| Ligue 1 | 639 | 0.9912 | **0.9880** | −0.0032 |
| **TODAS** | **3650** | **0.9894** | **0.9862** | **−0.0033** |

**PROMOVIDO** — IC 95% [−0.0054, −0.0011], p = 0.003. Mejora en cuatro de las
cinco ligas, lo que descarta que sea un artefacto de una competición.

Es la **primera promoción del proyecto**. El gate llevaba tres rechazos, y esa
es exactamente la señal de que no reparte títulos por simpatía.

Detalle con su punto de ironía: la excepción es la Premier (+0.0005), que es
justo la liga donde se descubrió la hipótesis. Una pista encontrada mirando una
competición resultó valer para las otras cuatro y no para ella.

### Qué corre en cinco ligas y qué no

El **loop de producción** (ingesta, predicción, scoring) y el **gate** corren
sobre las cinco. Los scripts de análisis histórico —el backtest de la F2, el
diagnóstico, los mercados y el valor— siguen sobre la Premier: cambiarlos
movería números ya reportados, y su valor es documental.

## Atacando las victorias locales, y el límite que apareció

El diagnóstico decía que el modelo pierde contra el mercado sobre todo en
victorias locales. Se atacó ese frente. **Los tres intentos fueron rechazados
por el gate, y el tercero por una razón que redefine el techo del proyecto.**

Primero se confirmó que el problema era real fuera del bloque donde se
encontró: en 2021/22–2023/24, temporadas que el diagnóstico nunca miró, la
brecha en locales es +0.0333. No era un artefacto.

Y se identificó la causa: **no es el nivel, es la discriminación.** El modelo da
43.6% de probabilidad media de local y el mercado 43.9% — prácticamente lo
mismo. Pero la correlación con el resultado es 0.3925 contra 0.4325. Separa
peor los partidos.

### Intento 1 — ventaja de local por equipo: es ruido

La variación entre equipos del residuo de local es 6.71%. La que produciría el
puro azar, dado el número de partidos, es 6.06%. **Compatible con ruido.** Meter
un parámetro de localía por equipo sería ajustar el azar y llamarlo modelo.

### Intento 2 — fuerza estimada con tiros a puerta: desplaza, no discrimina

Los tiros a puerta son señal menos ruidosa que los goles, así que se mezcló la
fuerza estimada con ambos. El log-loss de locales mejoraba muchísimo (0.7345 →
0.6089) — y era una trampa. La probabilidad media de local subía del 43.6% al
48.7% mientras la de empate se hundía del 23.0% al 15.9%, cuando la real es
22.5%. La correlación no se movía (0.3925 → 0.3932). Total: −0.0008, p = 0.52.
**Estaba moviendo masa, no separando partidos.**

### Intento 3 — recalibración con forma reciente: real, pero diminuta

Una capa logística que corrige las tres probabilidades con medias móviles de
tiros, tiros a puerta, corners y goles — lo que el motor Poisson no puede ver,
porque solo cuenta goles y un equipo que genera mucho sin marcar le resulta
idéntico a uno que no genera.

La primera versión repitió el error del intento 2 en forma sutil: mejoraba
locales −0.0368 (concluyente) y empeoraba empates +0.0129 y visitantes +0.0301
(también concluyentes). Se le quitó la capacidad de mover el nivel global
—sin interceptos, solo pesos— y **la ganancia sobrevivió**: correlación con
victoria local 0.3377 → 0.3502, probabilidad media quieta en 43.4%. Esa es la
prueba de que aporta información: si fuera desplazamiento, quitarle la palanca
lo habría borrado.

Total: **−0.0026 de log-loss. Rechazado, p = 0.409.**

### El límite que esto destapó

El gate no rechazó por capricho. Con 790 partidos **solo puede declarar
concluyente una diferencia de 0.0060 o mayor**. Para validar −0.0026 harían
falta ~4.279 partidos: unas **once temporadas de una sola liga**.

Y la distancia total del modelo al mercado es 0.0230. Es decir: **solo son
demostrables las mejoras que cierren más de una cuarta parte de esa distancia
de un golpe.** Cualquier avance incremental es invisible para este gate, no
porque el gate esté mal calibrado —su conservadurismo es correcto— sino porque
una liga no da suficientes partidos.

**El siguiente paso del proyecto no es un modelo mejor: son más datos.** Añadir
cuatro ligas grandes multiplicaría por cinco el bloque del gate y pondría estas
mejoras dentro de lo verificable. Cambiar de liga es una constante en
`config.py`; era el argumento de la F0 y aquí es donde se cobra.

## Atacando los empates: cinco candidatos, cinco rechazos, y una lección

Con cinco ligas, el diagnóstico dejó **una sola pista reforzada**: la brecha
contra el mercado en partidos que terminan en empate pasó de +0.0103 (Premier)
a +0.0207, concluyente. `scripts/13_draws.py` la atacó con la misma disciplina
que a los locales, y ahora con el gate de 3.650 partidos que aquel intento no
tenía.

**Primero, confirmar.** En 2122–2324 —temporadas que el diagnóstico no miró—
la brecha en empates es +0.0176, IC [+0.0108, +0.0243]. Real.

**Segundo, ¿nivel o discriminación?** Ni lo uno ni lo otro con claridad, y eso
ya era una señal:

| | empates reales | modelo p(D) | mercado p(D) | corr. modelo | corr. mercado |
|---|---|---|---|---|---|
| Cinco ligas | 25.5% | 24.6% | 25.0% | 0.114 | 0.121 |

El modelo pone 0.9 puntos menos de empate del que ocurre (el mercado, 0.5
menos), y discrimina apenas peor. Pero por liga la foto es otra: **Serie A**
subestima el empate en 2.8 puntos mientras la Premier lo clava, y
**Bundesliga** discrimina bastante peor que el mercado (0.098 contra 0.135)
mientras las demás casi igualan. Cinco enfermedades distintas bajo un mismo
síntoma.

**Tercero, los candidatos**, afinados en 2122–2324 y juzgados en 2425–2627
contra el campeón completo (motor + capa):

| Candidato | Qué es | dif. | IC 95% | brecha en empates después |
|---|---|---|---|---|
| A · desplazamiento | un parámetro que sube el logit de empate | −0.0002 | [−0.0008, +0.0005] | **−0.0055** |
| B · forma | dos features derivadas del motor (paridad, logit de empate) | −0.0004 | [−0.0015, +0.0006] | +0.0360 |
| C · A + B | | −0.0007 | [−0.0019, +0.0005] | +0.0018 |
| D · desplazamiento por liga | cinco parámetros, uno por liga | **+0.0002** | [−0.0009, +0.0013] | −0.0073 |
| E · D + B | | −0.0005 | [−0.0019, +0.0009] | −0.0005 |

**Los cinco rechazados.** Y la fila A es la que enseña: **cierra la brecha de
empates de +0.0300 a −0.0055 —el modelo pasa a ganarle al mercado en
empates— y el total se mueve 0.0002.** Lo que gana en empates lo devuelve en
locales y visitantes. Es el intento 2 de los locales al revés: mover masa, no
separar partidos. D, el de mejor pinta en el afinado, directamente pierde en el
gate: el +0.15 que Serie A eligió en 2122–2324 no se sostuvo en 2425–2627.
Cinco parámetros en vez de uno, y el primero que sobreajustó.

**La lección.** La brecha en empates no era una ineficiencia que se pudiera
cerrar reasignando probabilidad; era el *síntoma* de que el modelo sabe un poco
menos que el mercado en todo, y el empate —el resultado menos probable casi
siempre— es donde saber menos cuesta más caro en log-loss. Ni siquiera el
mercado discrimina empates bien (0.121). Cerrar ese frente exige información
que prediga empates, no una palanca de calibración. Los cinco desafíos están en
`ledger/challenges.csv`, con sus intervalos.

## ¿Hay valor real contra el mercado? (F7)

**No.** Y la forma en que no lo hay es más interesante que el titular.

> Esto es análisis, no una recomendación de apuesta. Mide si las
> probabilidades del modelo contienen información que el precio no tenga ya.

La expectativa estaba fijada de antemano: el modelo pierde contra el mercado por
0.0230 de log-loss, y eso es concluyente. Un modelo peor que el mercado no puede
batirlo de forma sistemática. Se midió igual, porque medir no es lo mismo que
suponer.

Se apuesta 1 unidad plana cuando el modelo ve valor esperado positivo, sobre las
5 temporadas de prueba, y se liquida con los resultados reales:

| Estrategia (cuota media, escenario realista) | Apuestas | ROI | IC 95% |
|---|---|---|---|
| EV > 0% | 2127 | **−8.50%** | [−15.86%, −0.87%] |
| EV > 2% | 1889 | −10.11% | [−17.78%, −2.19%] |
| EV > 5% | 1586 | −12.03% | [−20.71%, −3.19%] |
| EV > 10% | 1153 | −16.55% | [−26.69%, −5.95%] |
| *control: apostar a todo, sin criterio* | 5700 | *−6.03%* | *[−10.12%, −1.85%]* |

**Tres lecturas, y la tercera es la que importa.**

**El filtro de valor destruye dinero.** No es que no aporte: apostar según el
modelo (−8.50%) es *peor* que apostar a todos los partidos a ciegas (−6.03%). El
filtro selecciona precisamente los partidos donde el modelo más discrepa del
precio, y ahí el mercado tiene razón.

**Cuanto más exigente el filtro, peor.** De −8.50% a −16.55% al subir el umbral
de EV. Un umbral más alto no concentra el valor, concentra el error.

**La línea se mueve en contra.** El CLV medio es −1.31%: entre tomar el precio y
el cierre, el mercado se aleja de las selecciones del modelo. El CLV es el
indicador adelantado —no depende de si los resultados cayeron de cara o de
cruz— y dice lo mismo que el ROI.

### Una trampa que casi me como

El primer análisis usaba `Max*`, la mejor cuota entre todas las casas, y daba
apenas 0.67% de margen. Demasiado bueno: **el 28.6% de los partidos tenía margen
negativo, o sea arbitraje puro**. Un arbitraje real dura segundos; que apareciera
en uno de cada tres partidos delata que `Max*` no es un conjunto de precios
simultáneo, sino el máximo de cada resultado por separado a lo largo de todo el
pre-partido.

Se reportan los dos escenarios a propósito: **el modelo pierde incluso con
precios imposiblemente favorables**, lo que hace la conclusión mucho más firme
que si solo se hubiera probado con precios realistas.

### La hipótesis del diagnóstico, probada limpiamente

La F4 encontró que el modelo le gana al mercado en victorias visitantes. Probada
como estrategia sobre 2021/22–2023/24 —temporadas que el diagnóstico no miró—:
ROI −7.62%, intervalo [−23.73%, +9.85%]. **La ventaja en log-loss no se traduce
en dinero.** Ser un poco mejor calibrado en un segmento no alcanza para pagar el
margen.

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

### Las dos ventajas de arriba no existen

`scripts/11_diagnose_multi.py` repite el diagnóstico sobre las cinco ligas y le
mete a cada segmento el mismo bootstrap pareado que usa el gate (regla 6).
Escribe `ledger/diagnostics_multi.csv` y **no modifica nada de lo anterior**:
la tabla de una liga se deja como está, porque es lo que se publicó y su valor
ahora es documental.

La muestra pasa de 790 partidos con cuota de cierre a **3.650**, y con eso las
dos "ventajas" del párrafo anterior se caen:

| Segmento | 1 liga | 5 ligas | |
|---|---|---|---|
| Gana visitante | −0.0114 | +0.0053 | se da vuelta, y ya no se distingue de cero |
| Con tarjeta roja | −0.0039 | +0.0195 | se da vuelta, y ahora es demostrable |
| Empate | +0.0103 | +0.0207 | confirmada, y del doble |
| Gana local | +0.0410 | +0.0304 | confirmada |

Ninguna de las dos era una pista: era el azar de qué temporada tocó en una
liga. La de visitantes había llegado a ser **la hipótesis que la F7 salió a
probar**, y este es el mecanismo que la habría descartado antes de gastar la
sesión.

Lo que queda al ampliar es un resultado más incómodo y más útil: **18 de 20
grupos pierden contra el mercado con brecha demostrable, y el reparto es
parejo entre las cinco ligas** (de +0.0161 en la Premier a +0.0299 en la
Bundesliga, todas concluyentes). No hay un bolsillo donde atacar. La brecha es
del modelo, no de un segmento ni de una competición — y eso es una conclusión
que con 790 partidos no se podía sostener.

Esto genera hipótesis, no autoriza cambios. Cualquier idea que salga de aquí
pasa por el gate igual que las demás.

## El loop

Dos workflows de GitHub Actions, a distintas horas y con `concurrency` para que
nunca escriban a la vez:

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `score.yml` | 03:00 UTC diario | Ingiere resultados, los cruza con lo predicho, recalcula el marcador |
| `predict.yml` | cada 4 h (01, 05, 09, 13, 17, 21 UTC) | Baja los próximos partidos, ajusta el modelo y emite predicciones |
| `retrain.yml` | Lunes 06:00 UTC | Busca un retador, lo pasa por el gate, y diagnostica dónde falla |

Los días sin partidos ninguno de los dos commitea nada.

**La fuente publica los próximos partidos como una foto, no como una ventana
que rueda.** `fixtures.csv` es el único archivo de próximos partidos de
football-data.co.uk, y se regenera cada cierto tiempo cubriendo los días
siguientes al momento en que se escribe.

Medido el 2026-09-10 a las 03:12 UTC: el archivo tenía fecha de modificación del
**martes 08/09 a las 18:07 UTC** —33 horas antes— y cubría del 08 al 10 de
septiembre. Que una liga no aparezca significa que su siguiente jornada cae
fuera de esa foto, no que no se juegue.

Por eso el job de predecir corre **cada cuatro horas**: para recoger la foto
nueva poco después de que la fuente la escriba. Y por eso, después de cada
jornada, `05_score.py` comprueba si algún partido se jugó sin haber sido
predicho y lo registra en `ledger/missed.csv`. Si encuentra alguno, el workflow
queda en rojo: un partido sin predecir es un agujero en el track record, y un
agujero silencioso vale menos que ninguno.

**El punto ciego que tenía esta parte, y cómo se cerró.** Hasta el 2026-09-10,
una corrida sin partidos imprimía «No hay partidos por jugar sin predicción» y
terminaba en verde. Ese mensaje era **idéntico** en los dos casos que hay que
distinguir:

- no juega nadie en los próximos días → correcto, nada que hacer;
- la fuente lleva días sin regenerar el archivo → se están perdiendo jornadas.

Ese día el archivo llevaba 34 horas congelado y cubría hasta el 10, con la
jornada de las cinco ligas arrancando el 11. Tres corridas terminaron en verde
sin que nada lo dijera. Un proyecto cuya tesis es que el sistema de medición se
construye antes que el modelo tenía el punto ciego en su propia entrada.

Ahora `download_fixtures()` devuelve un `FixturesSnapshot` que conserva el
`Last-Modified` de la respuesta, y el log reporta **siempre** la edad de la
foto, qué ligas trae y qué rango cubre:

```
Fuente de fixtures: escrito 2026-09-08 18:07 UTC, hace 34 h · 18 partidos del 2026-09-08 al 2026-09-10
  ligas en el archivo: E1:9, E2:1, G1:1, N1:3, P1:2, SC0:2
  NINGUNA de las nuestras (E0, SP1, D1, I1, F1) esta en la foto.
  AVISO: la foto lleva 34 h sin regenerarse.
```

El umbral es `FIXTURES_STALE_HOURS`, 24 h. **Sin cabecera `Last-Modified` se
asume rancio**: no poder comprobar la frescura no es lo mismo que estar fresco,
y esa es la misma lógica de fallar cerrado que usa el guardia de pre-commit.

Esto no arregla que la foto sea vieja —eso solo lo arregla cambiar de fuente
para los fixtures— pero convierte un fallo silencioso en uno que se ve.

### Y el mismo día, se cambió de fuente para los fixtures

El detector duró unas horas en producción: a la siguiente lectura la foto
llevaba **49 h** congelada y la jornada arrancaba al día siguiente. Los próximos
partidos vienen ahora de **fixturedownload.com**, un CSV por liga con la
temporada completa (380 partidos las de 20 equipos, 306 las de 18), hora de
kickoff en UTC, y sin registro ni API key. Football-data.co.uk sigue siendo la
fuente del histórico, de los resultados y de las **cuotas de cierre** — eso no
cambia, y es lo que obliga a lo que viene.

**Los nombres son el costo real del cambio.** El `match_id` se construye con la
fecha y los nombres de los dos equipos, y el resultado va a llegar desde
football-data.co.uk con *sus* nombres: `Sevilla`, `Ath Bilbao`, `Man United`.
Si el fixture se hubiera escrito como `Sevilla FC`, el id sería otro, la
predicción nunca se conectaría con el resultado, y por la regla 3 tampoco se
podría corregir. `src/marcador/aliases.py` traduce los 96 equipos al
vocabulario canónico **antes** de crear el id. Un nombre que la tabla no
reconozca **salta el partido con aviso** — nunca se adivina, porque un id
equivocado es una predicción huérfana e inmutable, y `05_score.py` lo va a
reportar en `missed.csv` cuando se juegue.

Se comprobó sobre 99 partidos ya jugados que la fecha UTC de la fuente nueva
coincide con la que guarda football-data.co.uk en los 99.

**Lo que la temporada completa obligó a añadir: un tope hacia adelante.** Con
la fuente anterior no hacía falta, mostraba tres días. Con toda la temporada a
la vista, `04_predict.py` habría emitido 1.606 predicciones de golpe — un
partido de mayo predicho con el modelo de septiembre, y como una predicción
escrita no se reemplaza, esa sería la que contaría. Ahora se predice solo lo
que cae en los próximos `FIXTURES_LOOKAHEAD_DAYS` (3) y cuyo kickoff no haya
pasado. Cada partido se predice lo más cerca posible del kickoff, no lo más
pronto posible.

**Lo que no se pudo verificar.** fixturedownload.com no publica términos de uso
(solo tiene `/privacy`) ni dice de dónde saca los datos. Se usa como puente,
detrás de una capa de proveedor (`fixtures.py`) diseñada para que cambiar a una
API con términos explícitos sea reemplazar una función y la tabla de alias.

### Los mercados over/under en vivo: tarjetas, goles 2.5 y tiros a puerta

Es la F5 puesta a emitir, y solo una parte de ella. De los cuatro mercados que
`08_markets.py` midió en backtest, **tarjetas amarillas es el único que le gana
a la frecuencia base de forma concluyente** en sus tres líneas (+0.018 a
+0.032 de log-loss, p < 0.04). Goles, corners y tiros no. Por eso se emite
tarjetas y no los otros; la decisión está en `LIVE_MARKETS` de `config.py`, con
las líneas (2.5, 3.5, 4.5) y el `w` de encogimiento que la F5 eligió.

Tres cosas que este mercado hace distinto del 1X2, y por qué:

- **Firma con su propio nombre.** `dc-xi0020-reg002-norho+w-f5`, no el del
  campeón. Ni la corrección `rho` ni la capa de recalibración aplican a
  tarjetas; llamarlo igual sería decir que el modelo de tarjetas pasó por un
  gate que no existe.
- **La referencia se emite como un modelo más.** La fuente no publica cuota de
  tarjetas, así que no hay techo de mercado. Lo que hay es la frecuencia base
  de la liga —cuántos partidos pasan de 3.5 amarillas—, y el loop la escribe en
  el ledger como `base-freq-v1` con sus propias filas. Así `05_score.py` la
  evalúa con el mismo código que a cualquier modelo, y el dashboard puede decir
  «modelo contra base, mismos N partidos» sin un cálculo aparte que nadie pueda
  auditar desde el ledger.
- **El `w` se re-afinó en cinco ligas el mismo día, y cambió.** Los valores
  con los que salió (0.9 / 0.8 / 0.8) venían de la F5 sobre la Premier.
  `scripts/12_markets_multi.py` repite el afinado con las pérdidas de las cinco
  ligas juntas y escribe `ledger/markets_multi.csv`. Resultado: **0.7 / 0.6 /
  0.6**. Y el detalle que lo explica: por liga, la Premier vuelve a elegir
  exactamente 0.9 / 0.8 / 0.8 — las otras cuatro eligen entre 0.3 y 0.7. El `w`
  heredado no era "el del mercado", era el de la única liga que se había
  mirado, y sobreconfiaba en el modelo en las demás. Las primeras 43
  predicciones salieron con `w-f5` y son inmutables; desde entonces se emite
  con `w-5l`, y `05_score.py` evalúa a las dos.

**Y lo que el afinado en cinco ligas dijo de los otros tres mercados.** Con una
liga, solo tarjetas le ganaba a la base de forma concluyente. Con cinco —~3.500
partidos en el bloque de prueba en vez de 760— **le ganan los cuatro**, cada
línea con p < 0.001:

| Mercado | mejor línea | gana a la base | IC 95% |
|---|---|---|---|
| Tarjetas amarillas | 3.5 | +0.0278 | [+0.0221, +0.0335] |
| Tiros a puerta | 9.5 | +0.0213 | [+0.0150, +0.0276] |
| Goles | 3.5 | +0.0116 | [+0.0066, +0.0166] |
| Corners | 8.5 | +0.0095 | [+0.0052, +0.0137] |

Es el corolario de la regla 6 por tercera vez en el proyecto: los "no
concluyentes" de la F5 no decían que el modelo no aportara en goles, corners y
tiros; decían que 760 partidos no alcanzaban para verlo. Tarjetas sigue siendo
el mercado de mayor ganancia y por eso sigue siendo el único en vivo; tiros a
puerta es el siguiente candidato.

`results.csv` guarda ahora `yellows` (el total del partido) junto al marcador, y
`metrics.csv` lleva una fila por (modelo, mercado, `live`). En el dashboard hay
una sección por mercado: probabilidad de over por línea para lo que viene, y
para lo jugado, cuánto le dio el modelo y cuánto la referencia a lo que pasó.

**Goles over/under 2.5 se emite desde el 2026-09-11, y por una razón distinta a
la de tarjetas:** es el único mercado nuevo con cuota de cierre en la fuente.
Contra la frecuencia base cualquier modelo decente gana; contra el mercado es la
prueba de verdad, y en la Premier el modelo perdía por 0.0038. `results.csv`
guarda `market_o25`/`market_u25` (probabilidad implícita de cierre, sin margen)
y el marcador en vivo evalúa al mercado sobre los mismos partidos, igual que en
el 1X2. Solo la línea 2.5, a propósito: 1.5 y 3.5 no tienen cuota y solo se
medirían contra la base, que es lo que tarjetas ya hace. Firma como
`dc-xi0020-reg002-rho+goles-w-5l` — con rho, porque goles lo usa, y con el
nombre del mercado en el sufijo porque el slug quedaría peligrosamente parecido
al del campeón del 1X2. `w` = 0.7, el de cinco ligas.

**Tiros a puerta se emite desde el 2026-09-11** (`dc-xi0020-reg002-norho+sot-w-5l`,
líneas 7.5 / 8.5 / 9.5, `w` = 0.6 / 0.7 / 0.7 de cinco ligas). Es el segundo
mercado de mayor ganancia sobre la base; sin cuota en la fuente, se mide solo
contra ella. `results.csv` guarda `sot`, el total del partido. Con esto los
cuatro mercados de la F5 que le ganan a la base en cinco ligas están en vivo,
menos corners, que es el de señal más débil.

### La salud de la fuente queda en el ledger

Desde el 2026-09-11, cada corrida de `04_predict.py` deja una fila por liga en
`ledger/source_health.csv`: cuántos partidos hay en la ventana, cuántos sin hora
confirmada, hasta qué fecha llega el archivo, cuánto llevaba sin regenerarse, y
si hubo error de descarga o nombres sin alias. Hasta ese día todo eso vivía
solo en el log de Actions, que expira; la pregunta «¿cuántas veces estuvo mal
la fuente?» no tenía respuesta con datos. Cuesta un commit por corrida aunque
no haya predicción nueva (el mensaje lo distingue: «salud de la fuente»), y es
el precio de poder juzgar la fuente nueva contra la vieja con una serie y no
con una anécdota. El dashboard muestra la última corrida y cuenta las que
tuvieron problema.

### «0 partidos jugados» con cuatro partidos ya terminados

El sábado 12/09 por la mañana el dashboard decía «Ya jugados: 0» con los cuatro
partidos del viernes ya terminados. Nada estaba roto: `score.yml` había corrido,
había re-bajado la temporada y la fuente de resultados llevaba desde el lunes
sin regenerar el archivo (`Last-Modified` del 07/09, verificado a mano). La
fuente de resultados no publica en tiempo real, y el marcador solo puede
cruzar lo que ella trae.

El problema era el mismo punto ciego del 10/09, ahora del lado de los
resultados: el «0» no distinguía «no se jugó nada» de «se jugó y la fuente no
lo ha publicado». Se cerró en dos partes:

- El dashboard calcula **cuántos partidos predichos ya se jugaron y aún no
  tienen resultado** con la hora de `fixtures.csv` (kickoff + 2 h), no con la
  fuente de resultados, que es justo la que puede ir atrasada. Lo muestra al
  lado de «Ya jugados» y los lista aparte de los próximos.
- Cada corrida de `05_score.py` deja una fila por liga en
  `ledger/results_health.csv`: partidos con resultado en el archivo, hasta qué
  fecha llega, cuánto llevaba sin regenerarse y cuántos partidos esperan. Es la
  serie que responde «¿cuánto tarda la fuente en publicar?», y cuesta un commit
  por día aunque no haya resultados («salud de resultados»).

Un botón para «actualizar» desde el dashboard se descartó: no arreglaría nada
(la fuente seguiría sin los partidos), la app es pública y el botón necesitaría
un token de GitHub, y solo el runner escribe en el ledger. El botón que sí
existe es **Run workflow** en Actions, y hoy tampoco haría nada.

### `kickoff_utc` decía UTC y era hora del Reino Unido

La fuente del histórico no documenta la zona de su columna `Time`. Se midió
contra la hora UTC de la fuente de fixtures sobre 144 partidos ya jugados de las
cinco ligas: **+1 hora exacta en los 144**. Es hora del Reino Unido —BST en
verano, GMT en invierno—, no UTC ni la hora local de cada país (España o Italia
habrían dado +2). La ingesta la convierte ahora con `Europe/London → UTC`, con
zona horaria real y no una resta fija, para que el cambio de horario no la
rompa dos veces al año. `match_date` no se toca: es la fecha de la fuente y
forma el `match_id`. Verificado tras re-ingestar: 144 de 144 a cero.

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
./.venv/bin/python scripts/11_diagnose_multi.py      # lo mismo en 5 ligas, con intervalos
./.venv/bin/python scripts/12_markets_multi.py       # los 4 mercados en 5 ligas, re-afina w
./.venv/bin/python scripts/13_draws.py --dry-run     # ataque a los empates, contra el gate
./.venv/bin/streamlit run dashboard/app.py           # dashboard en localhost:8501
```

El dashboard lee **solo el ledger**, nunca la base local. Si necesitara la base,
nadie de afuera podría reproducir lo que muestra.

**Sobre el despliegue en Streamlit Cloud.** Cada push a `main` lo redespliega
solo, pero **sin reiniciar el proceso de Python**: los módulos de `src/` que ya
estaban importados se quedan en memoria con su versión anterior. Un push que
añada un módulo nuevo, o que cambie lo que un módulo exporta, se rompe con un
`ImportError` hasta que se haga **Reboot app** desde «Manage app». Pasó el
2026-09-10 con `live_markets.py`; un clon limpio importaba sin problema.

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
  07_diagnose.py  donde pierde el campeon contra el mercado (1 liga)
  08_markets.py   backtest de corners, tarjetas y tiros
  11_diagnose_multi.py  lo mismo en 5 ligas, y si la brecha es demostrable
  12_markets_multi.py   los cuatro mercados en 5 ligas; re-afina el w de tarjetas
  13_draws.py     ataque a los empates: diagnostico, cinco candidatos, gate
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

## Fuentes de datos

**Histórico, resultados y cuotas:** [football-data.co.uk](https://football-data.co.uk)
— CSV por temporada y liga, gratuitos. Traen resultado, corners, tarjetas,
tiros, tiros a puerta, árbitro y cuotas de varias casas incluyendo las de
cierre.

**Próximos partidos:** [fixturedownload.com](https://fixturedownload.com) —
un CSV por liga con la temporada completa y hora en UTC. Desde el 2026-09-10;
antes venían del `fixtures.csv` de football-data.co.uk, que es una foto de
tres días que la fuente regenera cuando quiere (ver «Y el mismo día, se cambió
de fuente»). Los nombres de equipo se traducen en `aliases.py`.

Dos cosas que cuestan tiempo si uno no las sabe, y que ya están resueltas en el
código:

- El subdominio `www.` responde **503** a peticiones programáticas. El dominio
  pelado responde 200.
- El formato de fecha cambia entre temporadas: unas traen `dd/mm/yyyy` y otras
  `dd/mm/yy`. La columna `Time` solo existe desde 2019/20.

## Cómo está construido, en una frase por pieza

- **Los datos crudos no entran al repo.** `data/` está en `.gitignore`; lo que
  se publica son predicciones y métricas derivadas.
- **Las predicciones son inmutables**, y no por disciplina: la base de datos
  aborta cualquier `UPDATE` o `DELETE` sobre ellas con un trigger.
- **Ninguna feature usa información del futuro**, y también lo impone la base:
  una predicción cuyo corte de información sea posterior al partido se rechaza.
- **Todo backtest es walk-forward**, agrupado por fecha para que dos partidos
  del mismo día no se filtren información entre sí.
- **Ninguna comparación entre modelos se hace por promedio**: todas pasan por un
  bootstrap pareado, porque una diferencia de 0.002 de log-loss sobre 1700
  partidos cabe holgada dentro del ruido.
- **El modelo en producción vive en un archivo versionado, no en el código**, que
  es lo que permite que el gate promueva sin intervención humana.

## Licencia

MIT para el código — ver [LICENSE](LICENSE). Los datos son de sus respectivas
fuentes y no se redistribuyen aquí.
