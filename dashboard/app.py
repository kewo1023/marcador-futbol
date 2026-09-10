"""Dashboard del marcador. Lee SOLO el ledger versionado, nunca la base local.

    ./.venv/bin/streamlit run dashboard/app.py

Es a proposito: si el dashboard necesitara la base de datos, nadie de afuera
podria reproducir lo que muestra. Leyendo del ledger, cualquiera que clone el
repo ve exactamente los mismos numeros sin bajar un solo dato de la fuente.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marcador import ledger, promotion              # noqa: E402
from marcador.config import LEAGUES                 # noqa: E402

st.set_page_config(page_title="Marcador", page_icon="⚽", layout="wide")


@st.cache_data(ttl=300)
def load():
    return (pd.DataFrame(ledger.read_predictions()),
            pd.DataFrame(ledger.read_results()),
            pd.DataFrame(ledger._read(ledger.LEDGER_METRICS)))


preds, results, metrics = load()
champ = promotion.read_champion()
PRODUCTION_MODEL = champ["raw"]["model_version"] if champ else "(sin campeon)"

st.title("Marcador antes que modelo")
st.caption(f"{len(LEAGUES)} ligas · modelo en producción `{PRODUCTION_MODEL}` · "
           "todo lo que se ve sale del ledger versionado en git")

# --- El campeon y sus desafios ----------------------------------------------
st.subheader("Campeón y desafíos")
st.caption("Cada semana se busca una configuración nueva y se la enfrenta al "
           "campeón sobre partidos que ninguna de las dos vio. El campeón "
           "conserva el título salvo que lo derroten de forma concluyente: un "
           "empate estadístico lo gana el campeón. Los rechazos se muestran "
           "porque son la prueba de que el gate hace algo.")
if champ:
    c = champ["raw"]
    st.markdown(f"**En producción:** `{c['model_version']}` · "
                f"desde {c['promoted_at'][:10]} · _{c['promoted_because']}_")
challenges = pd.DataFrame(promotion.read_challenges())
if challenges.empty:
    st.write("Todavía no se ha corrido ningún desafío.")
else:
    view = challenges[["decided_at", "challenger", "champion", "diff",
                       "ci_low", "ci_high", "p_value", "decision", "n_matches"]].copy()
    view["decided_at"] = view["decided_at"].str[:10]
    view = view.rename(columns={"decided_at": "fecha", "challenger": "retador",
                                "champion": "campeón", "diff": "diferencia",
                                "p_value": "p", "decision": "veredicto",
                                "n_matches": "partidos"})
    st.dataframe(view.iloc[::-1], use_container_width=True, hide_index=True)

# --- Donde falla ------------------------------------------------------------
diag_path = ledger.LEDGER_DIR / "diagnostics.csv"
if diag_path.exists():
    st.subheader("Dónde pierde contra el mercado")
    st.caption("`brecha` es cuánto peor que el mercado en ese grupo. `aporta` "
               "es cuánto de la brecha total viene de ahí (brecha × tamaño). "
               "El grupo que hay que atacar es el que más aporta, no el de "
               "mayor brecha. Esto genera hipótesis; no autoriza cambios: "
               "cualquier idea que salga de aquí pasa por el gate igual.")
    diag = pd.DataFrame(ledger._read(diag_path))
    if not diag.empty:
        diag = diag.astype({"n": int, "modelo": float, "mercado": float,
                            "brecha": float, "peso": float})
        seg = st.selectbox("Segmento", sorted(diag["segmento"].unique()))
        sub = diag[diag["segmento"] == seg].sort_values("peso", ascending=False)
        st.dataframe(sub[["grupo", "n", "modelo", "mercado", "brecha", "peso"]]
                     .rename(columns={"peso": "aporta"}),
                     use_container_width=True, hide_index=True)

st.divider()

if preds.empty:
    st.info("El ledger todavía no tiene predicciones en vivo. El loop las "
            "escribe cuando los próximos partidos entren en la ventana de la "
            "fuente, que es de pocos días. Lo de arriba no depende de eso: "
            "sale del backtest.")
    st.stop()

preds["prob"] = preds["prob"].astype(float)
# El match_id empieza por el codigo de liga, asi que la liga se deduce sin
# guardar una columna aparte.
preds["liga"] = preds["match_id"].str.split("_").str[0]
played = set(results["match_id"]) if not results.empty else set()

# --- Estado general ---------------------------------------------------------
live = metrics[metrics["eval_set"] == "live"] if not metrics.empty else pd.DataFrame()
test = metrics[metrics["eval_set"] == "test"] if not metrics.empty else pd.DataFrame()

c1, c2, c3, c4 = st.columns(4)
n_matches = preds["match_id"].nunique()
c1.metric("Partidos predichos", n_matches)
c2.metric("Ya jugados", len(played))
if not live.empty:
    row = live[live["model_version"] == PRODUCTION_MODEL]
    if not row.empty:
        ll = float(row.iloc[0]["log_loss"])
        ref = test[test["model_version"] == "baseline-elo-v1"]
        delta = None
        if not ref.empty:
            delta = f"{ll - float(ref.iloc[0]['log_loss']):+.4f} vs Elo"
        c3.metric("log-loss en vivo", f"{ll:.4f}", delta, delta_color="inverse")
        c4.metric("Acierto", f"{float(row.iloc[0]['accuracy'])*100:.0f}%")

if len(played) < 100:
    st.warning(f"Solo {len(played)} partidos jugados. Un log-loss con tan pocos "
               "datos se mueve muchísimo y no significa nada todavía; hacen "
               "falta ~100 para que el número se estabilice.")

# --- Próximos partidos ------------------------------------------------------
st.subheader("Próximos partidos")
upcoming = preds[~preds["match_id"].isin(played)]
if upcoming.empty:
    st.write("Nada pendiente ahora mismo.")
else:
    wide = (upcoming.pivot_table(index=["match_date", "home_team", "away_team"],
                                 columns="outcome", values="prob")
            .reset_index().rename(columns={"match_date": "fecha",
                                           "home_team": "local",
                                           "away_team": "visitante",
                                           "H": "gana local", "D": "empate",
                                           "A": "gana visitante"}))
    st.dataframe(wide.style.format({"gana local": "{:.1%}", "empate": "{:.1%}",
                                    "gana visitante": "{:.1%}"}),
                 use_container_width=True, hide_index=True)

# --- Lo ya jugado -----------------------------------------------------------
if played:
    st.subheader("Partidos ya jugados")
    done = preds[preds["match_id"].isin(played)]
    wide = done.pivot_table(index="match_id", columns="outcome",
                            values="prob").reset_index()
    merged = results.merge(wide, on="match_id")
    merged["marcador"] = merged["fthg"].astype(str) + "-" + merged["ftag"].astype(str)
    merged["le dio al resultado"] = [r[r["ftr"]] for _, r in merged.iterrows()]
    view = (merged[["match_date", "home_team", "away_team", "marcador", "ftr",
                    "H", "D", "A", "le dio al resultado"]]
            .sort_values("match_date", ascending=False)
            .rename(columns={"match_date": "fecha", "home_team": "local",
                             "away_team": "visitante", "ftr": "resultado"}))
    st.dataframe(view.style.format({"H": "{:.1%}", "D": "{:.1%}", "A": "{:.1%}",
                                    "le dio al resultado": "{:.1%}"}),
                 use_container_width=True, hide_index=True)

    # --- Calibración --------------------------------------------------------
    st.subheader("Calibración")
    st.caption("Cuando el modelo dice 70%, ¿pasa 7 de cada 10 veces? "
               "Los puntos deberían caer sobre la diagonal. Es el gráfico que "
               "revela si el modelo es exagerado o tímido, que ninguna métrica "
               "de un solo número muestra.")
    rows = []
    for _, r in done.iterrows():
        actual = results.loc[results["match_id"] == r["match_id"], "ftr"].iloc[0]
        rows.append({"prob": r["prob"], "acerto": int(r["outcome"] == actual)})
    cal = pd.DataFrame(rows)
    cal["bucket"] = (cal["prob"] * 10).astype(int).clip(0, 9) / 10 + 0.05
    grp = cal.groupby("bucket").agg(prometio=("prob", "mean"),
                                    ocurrio=("acerto", "mean"),
                                    n=("acerto", "size")).reset_index()
    grp = grp[grp["n"] >= 3]
    if grp.empty:
        st.write("Aún no hay suficientes predicciones por bucket para dibujarla.")
    else:
        chart = grp.set_index("prometio")[["ocurrio"]]
        chart["ideal"] = chart.index
        st.line_chart(chart)
        st.dataframe(grp.style.format({"prometio": "{:.1%}", "ocurrio": "{:.1%}"}),
                     use_container_width=True, hide_index=True)

# --- Los otros mercados -----------------------------------------------------
mk_path = ledger.LEDGER_DIR / "markets.csv"
if mk_path.exists():
    st.subheader("Otros mercados")
    st.caption("El mismo motor apuntado a otra columna. `w` es cuánto se le "
               "cree al modelo frente a la frecuencia base: bajo significa que "
               "la señal es débil en ese mercado. Corners, tarjetas y tiros no "
               "tienen cuota en la fuente, así que se miden solo contra la "
               "base — se sabe si aportan, no cuánto les falta.")
    mk = pd.DataFrame(ledger._read(mk_path))
    if not mk.empty:
        mk = mk.astype({"linea": float, "n": int, "w": float,
                        "log_loss_base": float, "log_loss_encogido": float,
                        "gana_a_base": float, "p_value": float})
        mk["veredicto"] = ["gana a la base" if (c == "si" and g > 0) else "no concluyente"
                           for c, g in zip(mk["concluyente"], mk["gana_a_base"])]
        st.dataframe(mk[["etiqueta", "linea", "w", "log_loss_base",
                         "log_loss_encogido", "gana_a_base", "p_value",
                         "veredicto"]]
                     .rename(columns={"etiqueta": "mercado",
                                      "log_loss_base": "base",
                                      "log_loss_encogido": "modelo",
                                      "gana_a_base": "gana", "p_value": "p"}),
                     use_container_width=True, hide_index=True)

# --- Referencia del backtest ------------------------------------------------
if not test.empty:
    st.subheader("Referencia del backtest")
    st.caption("Temporadas de prueba de la F2. Es el contexto sin el cual un "
               "log-loss suelto no dice nada.")
    view = test[["model_version", "log_loss", "brier", "accuracy", "n_matches"]]
    view = view.astype({"log_loss": float, "brier": float,
                        "accuracy": float}).sort_values("log_loss")
    st.dataframe(view.rename(columns={"model_version": "modelo",
                                      "n_matches": "partidos"}),
                 use_container_width=True, hide_index=True)
