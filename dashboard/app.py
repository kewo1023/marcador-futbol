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

from marcador import ledger                        # noqa: E402
from marcador.config import LEAGUE, PRODUCTION_MODEL  # noqa: E402

st.set_page_config(page_title="Marcador", page_icon="⚽", layout="wide")


@st.cache_data(ttl=300)
def load():
    return (pd.DataFrame(ledger.read_predictions()),
            pd.DataFrame(ledger.read_results()),
            pd.DataFrame(ledger._read(ledger.LEDGER_METRICS)))


preds, results, metrics = load()

st.title("Marcador antes que modelo")
st.caption(f"Liga {LEAGUE} · modelo en producción `{PRODUCTION_MODEL}` · "
           "todo lo que se ve sale del ledger versionado en git")

if preds.empty:
    st.info("El ledger todavía no tiene predicciones. El loop las escribe "
            "cuando la fuente publique los próximos partidos "
            "(en parón de selecciones no hay ninguno).")
    st.stop()

preds["prob"] = preds["prob"].astype(float)
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
