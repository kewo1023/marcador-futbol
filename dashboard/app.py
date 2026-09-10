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

from marcador import ledger, live_markets, promotion  # noqa: E402
from marcador.config import BASE_MODEL_VERSION as BASE_MODEL, LEAGUES  # noqa: E402

st.set_page_config(page_title="Marcador", page_icon="⚽", layout="wide")


@st.cache_data(ttl=300)
def load():
    return (pd.DataFrame(ledger.read_predictions()),
            pd.DataFrame(ledger.read_results()),
            pd.DataFrame(ledger._read(ledger.LEDGER_METRICS)),
            pd.DataFrame(ledger.read_fixtures()))


def with_kickoff(df, fixtures):
    """Cambia la columna `fecha` por fecha y hora UTC cuando el ledger la tiene.

    La hora vive en ledger/fixtures.csv, aparte de las predicciones, porque
    cambia (aplazamientos) y las predicciones no. Un partido sin hora en el
    ledger —los emitidos antes de que existiera ese archivo, o los que la liga
    aun no confirmo— se queda con la fecha sola.
    """
    if fixtures.empty or "kickoff_utc" not in fixtures:
        return df
    hours = fixtures.set_index("match_id")["kickoff_utc"]
    ko = df["match_id"].map(hours).fillna("")
    df = df.copy()
    df["fecha"] = [
        (k.replace("T", " ") + " UTC") if k else d
        for k, d in zip(ko, df["match_date"])]
    return df


# Local primero, empate en medio, visitante al final: el orden en que se lee
# un partido. Se aplica igual a los proximos y a los ya jugados.
COLS_1X2 = {"H": "gana local", "D": "empate", "A": "gana visitante"}
ORDER_1X2 = ["gana local", "empate", "gana visitante"]

preds, results, metrics, fixtures = load()
champ = promotion.read_champion()
PRODUCTION_MODEL = champ["raw"]["model_version"] if champ else "(sin campeon)"
# El modelo de tarjetas en produccion. Puede convivir en el ledger con
# versiones anteriores (el w cambio el 10/09); aqui se muestra solo esta y
# 05_score evalua a todas.
YC_MODEL = live_markets.market_version(champ["config"], "tarjetas") if champ else ""

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

# Desde el 2026-09-10 el ledger trae dos mercados. Todo lo que sigue hasta
# 'Tarjetas amarillas' es el 1X2; las filas de tarjetas se apartan aqui.
all_preds = preds
preds = all_preds[all_preds["market"] == "1X2"]
yc = all_preds[all_preds["market"].str.startswith("TARJETAS_")]

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
        # La referencia que importa es el mercado sobre ESTOS mismos partidos.
        # Elo del backtest solo se muestra si el mercado aun no tiene filas.
        mkt = live[live["model_version"] == "market-avgclose-v1"]
        ref = test[test["model_version"] == "baseline-elo-v1"]
        delta = None
        if not mkt.empty:
            delta = f"{ll - float(mkt.iloc[0]['log_loss']):+.4f} vs mercado"
        elif not ref.empty:
            delta = f"{ll - float(ref.iloc[0]['log_loss']):+.4f} vs Elo (backtest)"
        c3.metric("log-loss en vivo", f"{ll:.4f}", delta, delta_color="inverse")
        c4.metric("Acierto", f"{float(row.iloc[0]['accuracy'])*100:.0f}%")
        if not mkt.empty:
            st.caption(f"Mercado sobre los mismos {mkt.iloc[0]['n_matches']} "
                       f"partidos: {float(mkt.iloc[0]['log_loss']):.4f}. "
                       "Negativo = el modelo va por delante. Con pocos partidos "
                       "cambia de signo de una jornada a otra; no es concluyente "
                       "hasta que pase por el bootstrap.")

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
    wide = (upcoming.pivot_table(index=["match_id", "match_date", "home_team",
                                        "away_team"],
                                 columns="outcome", values="prob")
            .reset_index().rename(columns=COLS_1X2))
    wide = with_kickoff(wide, fixtures).sort_values(["match_date", "fecha"])
    view = (wide.rename(columns={"home_team": "local", "away_team": "visitante"})
            [["fecha", "local", "visitante"] + ORDER_1X2])
    st.dataframe(view.style.format({c: "{:.1%}" for c in ORDER_1X2}),
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
    # 'acerto' = el resultado real era el mas probable segun el modelo. Es lo
    # primero que pregunta cualquiera, y por eso se muestra; pero es accuracy,
    # y accuracy no decide nada (regla 5): un 34-33-33 que 'acierta' no sabia
    # nada, y un 60% que falla una vez de cada tres esta haciendo su trabajo.
    # Lo que si mide es la columna de al lado: cuanta probabilidad le dio a
    # lo que paso. Ese numero es el que entra al log-loss.
    merged["acerto"] = [
        "✓" if max("HDA", key=lambda o: r[o]) == r["ftr"] else "✗"
        for _, r in merged.iterrows()]
    merged["resultado"] = merged["ftr"].map({"H": "local", "D": "empate",
                                              "A": "visitante"})
    # El mercado, si el ledger lo trae para ese partido: cuanta probabilidad
    # le dio la cuota de cierre a lo que paso, y la diferencia con el modelo.
    # Es la comparacion que define el proyecto, partido a partido.
    def _mkt(r):
        v = r.get("market_" + r["ftr"].lower(), "")
        return float(v) if v not in ("", None) and v == v else None
    merged["mercado le dio"] = [_mkt(r) for _, r in merged.iterrows()]
    merged["vs mercado"] = merged["le dio al resultado"] - merged["mercado le dio"]
    merged = with_kickoff(merged.rename(columns=COLS_1X2), fixtures)
    view = (merged.sort_values(["match_date", "fecha"], ascending=False)
            .rename(columns={"home_team": "local", "away_team": "visitante"})
            [["fecha", "local", "visitante", "marcador", "resultado", "acerto"]
             + ORDER_1X2 + ["le dio al resultado", "mercado le dio", "vs mercado"]])
    st.caption("`acertó` es si el resultado real era el más probable. Es "
               "contexto, no criterio. Las que cuentan son las tres últimas: "
               "cuánta probabilidad puso el modelo en lo que pasó, cuánta puso "
               "la cuota de cierre, y la diferencia. **Positivo = el modelo vio "
               "más que el mercado en ese partido.** Sumado sobre cientos de "
               "partidos, eso es el log-loss de arriba.")
    st.dataframe(view.style.format({c: "{:.1%}" for c in ORDER_1X2}
                                   | {"le dio al resultado": "{:.1%}",
                                      "mercado le dio": "{:.1%}",
                                      "vs mercado": "{:+.1%}"}, na_rep="—")
                 .map(lambda v: ("color: #3fb950" if v > 0 else "color: #f85149")
                      if isinstance(v, float) and v == v else "",
                      subset=["vs mercado"]),
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
# --- Tarjetas amarillas en vivo ---------------------------------------------
# El segundo mercado que se emite. La referencia aqui no es el mercado (la
# fuente no publica cuota de tarjetas) sino la frecuencia base, que el loop
# emite como un modelo mas (base-freq-v1) para que se compare igual.
if not yc.empty:
    st.subheader("Tarjetas amarillas")
    st.caption(f"Modelo en produccion para tarjetas: `{YC_MODEL}`")
    st.caption("Mismo motor, otra columna. `>3.5` es la probabilidad de que el "
               "partido tenga cuatro amarillas o más. La referencia es la "
               "frecuencia base de la liga —no hay cuota de tarjetas en la "
               "fuente—, así que aquí se sabe si el modelo aporta, no cuánto "
               "le falta para lo alcanzable. En el backtest fue el único "
               "mercado que le ganó a la base de forma concluyente.")
    yc = yc.copy()
    yc["linea"] = yc["market"].str.replace("TARJETAS_OU", "", regex=False)
    yc["linea"] = ">" + yc["linea"].str[0] + "." + yc["linea"].str[1]
    lines = sorted(yc["linea"].unique())
    yc_model = yc[(yc["model_version"] == YC_MODEL) & (yc["outcome"] == "OVER")]
    yc_base = yc[(yc["model_version"] == BASE_MODEL) & (yc["outcome"] == "OVER")]

    # Marcador de tarjetas: modelo contra base por linea, sobre lo jugado.
    live_yc = live[live["market"].str.startswith("TARJETAS_")] if not live.empty else pd.DataFrame()
    if not live_yc.empty:
        cols = st.columns(len(lines))
        for col, line in zip(cols, lines):
            code = "TARJETAS_OU" + line[1] + line[3]
            m = live_yc[(live_yc["market"] == code) & (live_yc["model_version"] == YC_MODEL)]
            b = live_yc[(live_yc["market"] == code) & (live_yc["model_version"] == BASE_MODEL)]
            if m.empty or b.empty:
                continue
            d = float(m.iloc[0]["log_loss"]) - float(b.iloc[0]["log_loss"])
            col.metric(f"log-loss {line} · {m.iloc[0]['n_matches']} partidos",
                       f"{float(m.iloc[0]['log_loss']):.4f}",
                       f"{d:+.4f} vs base", delta_color="inverse")

    yc_up = yc_model[~yc_model["match_id"].isin(played)]
    if not yc_up.empty:
        wide = (yc_up.pivot_table(index=["match_id", "match_date", "home_team",
                                         "away_team"],
                                  columns="linea", values="prob").reset_index())
        wide = with_kickoff(wide, fixtures).sort_values(["match_date", "fecha"])
        view = (wide.rename(columns={"home_team": "local", "away_team": "visitante"})
                [["fecha", "local", "visitante"] + lines])
        st.dataframe(view.style.format({l: "{:.1%}" for l in lines}),
                     use_container_width=True, hide_index=True)

    yc_done = yc_model[yc_model["match_id"].isin(played)]
    if not yc_done.empty and "yellows" in results:
        pick = st.selectbox("Línea", lines, index=min(1, len(lines) - 1),
                            key="yc_line")
        m_w = yc_done[yc_done["linea"] == pick].set_index("match_id")["prob"]
        b_w = yc_base[yc_base["linea"] == pick].set_index("match_id")["prob"]
        res = results[results["match_id"].isin(m_w.index)
                      & (results["yellows"].astype(str) != "")].copy()
        res["amarillas"] = res["yellows"].astype(int)
        thr = float(pick[1:])
        over = res["amarillas"] > thr
        p_m = res["match_id"].map(m_w)
        p_b = res["match_id"].map(b_w)
        # Lo que cada uno le dio a lo que paso: P(over) si hubo over, si no
        # 1 - P(over). Es la misma columna 'le dio al resultado' del 1X2.
        res["modelo le dio"] = p_m.where(over, 1 - p_m)
        res["base le dio"] = p_b.where(over, 1 - p_b)
        res["vs base"] = res["modelo le dio"] - res["base le dio"]
        res["paso"] = over.map({True: "over", False: "under"})
        res = with_kickoff(res, fixtures)
        view = (res.sort_values(["match_date", "fecha"], ascending=False)
                .rename(columns={"home_team": "local", "away_team": "visitante"})
                [["fecha", "local", "visitante", "amarillas", "paso",
                  "modelo le dio", "base le dio", "vs base"]])
        st.dataframe(view.style.format({"modelo le dio": "{:.1%}",
                                        "base le dio": "{:.1%}",
                                        "vs base": "{:+.1%}"}, na_rep="—")
                     .map(lambda v: ("color: #3fb950" if v > 0 else "color: #f85149")
                          if isinstance(v, float) and v == v else "",
                          subset=["vs base"]),
                     use_container_width=True, hide_index=True)

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

    # La misma medicion sobre las cinco ligas. La tabla de arriba es de una
    # sola y se deja como se publico; esta es la que manda, y dice otra cosa.
    mm_path = ledger.LEDGER_DIR / "markets_multi.csv"
    if mm_path.exists():
        mm = pd.DataFrame(ledger._read(mm_path))
        if not mm.empty:
            mm = mm.astype({"linea": float, "n": int, "w": float,
                            "log_loss_base": float, "log_loss_encogido": float,
                            "gana_a_base": float, "p_value": float})
            mm["veredicto"] = ["gana a la base" if (c == "si" and g > 0) else "no concluyente"
                               for c, g in zip(mm["concluyente"], mm["gana_a_base"])]
            st.caption("**Sobre las cinco ligas** (~3.500 partidos en vez de "
                       "760). Con una liga solo tarjetas era concluyente; con "
                       "cinco lo son los cuatro mercados. `w por liga` muestra "
                       "cuánto se le cree al modelo en cada una: la Premier es "
                       "la que más, y de ahí venía el `w` original.")
            st.dataframe(mm[["etiqueta", "linea", "w", "w_por_liga", "n",
                             "log_loss_base", "log_loss_encogido",
                             "gana_a_base", "p_value", "veredicto"]]
                         .rename(columns={"etiqueta": "mercado",
                                          "w_por_liga": "w por liga",
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
