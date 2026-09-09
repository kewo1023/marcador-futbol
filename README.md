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
| F2 | Motor Dixon-Coles | ⬜ |
| F3 | Loop automatizado (GitHub Actions + dashboard) | ⬜ |
| F4 | Reentreno con gate de promoción | ⬜ |
| F5 | Mercados nuevos: corners, tarjetas, tiros | ⬜ |
| F6 | Empaquetado y documentación | ⬜ |

## El marcador hoy

Backtest walk-forward sobre 11 temporadas de Premier League (2015/16 a
2025/26). Los tres son baselines: todavía no hay modelo propio.

| Modelo | log-loss ↓ | Brier ↓ | accuracy | partidos |
|---|---|---|---|---|
| Frecuencia base | 1.0662 | 0.6450 | 44.6% | 3800 |
| Elo | 0.9834 | 0.5852 | 54.8% | 3800 |
| Mercado (cierre, sin margen) | 0.9524 | 0.5637 | 55.1% | 4010 |

**Cómo se lee.** La frecuencia base es el piso: predice lo mismo para todos los
partidos. El mercado es el techo: incorpora toda la información pública más el
dinero profesional. Todo el espacio disponible entre los dos son 0.114 de
log-loss, y Elo —un rating de una sola línea de matemáticas— ya se come el 73%
de ese espacio.

Ese número es la vara real del proyecto: el modelo de la F2 no compite contra
la frecuencia base, compite contra Elo, y lo que queda por ganar son 0.031 de
log-loss. Saberlo desde ahora es exactamente para lo que sirve construir el
marcador primero.

`accuracy` se muestra como contexto y no decide nada — ver la regla 5 de
[CLAUDE.md](CLAUDE.md).

## Cómo correrlo

Requiere Python 3.11 o superior. La F1 corre solo con la librería estándar.

```bash
python3 scripts/01_ingest.py     # baja los CSV historicos -> data/marcador.sqlite
python3 scripts/02_baseline.py   # genera predicciones baseline y calcula el marcador
```

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
scripts/
  01_ingest.py  baja y carga
  02_baseline.py genera predicciones walk-forward y llena el marcador
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
