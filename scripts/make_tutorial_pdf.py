#!/usr/bin/env python3
"""Genera docs/TUTORIAL.pdf — la guia para quien no va a leer el repo.

    ./.venv/bin/python scripts/make_tutorial_pdf.py

El PDF se versiona, pero el generador tambien: un documento que no se puede
regenerar queda desactualizado la primera vez que cambia un numero.
"""
import subprocess
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,
                                PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

OUT = Path(__file__).resolve().parents[1] / "docs" / "TUTORIAL.pdf"


def repo_url():
    """La URL del repositorio, leida del remoto de git en vez de escrita aqui.

    No es un capricho: el nombre de usuario de GitHub esta en la lista de
    terminos que el hook pre-commit no deja entrar al repositorio, y con razon
    —protege el codigo de llevar datos personales incrustados—. Que el PDF sea
    el sitio donde ese dato SI debe aparecer no es motivo para saltarse el
    guardia: es motivo para no escribirlo en el codigo fuente.

    De paso queda mejor: si el repositorio se mueve, la URL se mueve con el.
    """
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"],
                             capture_output=True, text=True, check=True,
                             cwd=Path(__file__).resolve().parents[1]
                             ).stdout.strip()
    except Exception:                                   # noqa: BLE001
        return "(configura el remoto de git para que aparezca aqui)"
    return url.removesuffix(".git").replace("https://", "")


REPO = repo_url()

TINTA = colors.HexColor("#14201A")
SUAVE = colors.HexColor("#5D6862")
VERDE = colors.HexColor("#0E6146")
VERDE_SUAVE = colors.HexColor("#E4F0E9")
LINEA = colors.HexColor("#D3DBD2")
AMBAR = colors.HexColor("#F6EEDA")
AMBAR_LIN = colors.HexColor("#DFC98C")
AMBAR_TXT = colors.HexColor("#6B4E06")

ss = getSampleStyleSheet()


def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10.2, leading=15.4,
                textColor=TINTA, alignment=TA_LEFT, spaceAfter=7)
    base.update(kw)
    return ParagraphStyle(name, **base)


P = S("P")
LEAD = S("LEAD", fontSize=12.4, leading=18, textColor=SUAVE, spaceAfter=12)
H1 = S("H1", fontName="Helvetica-Bold", fontSize=19, leading=23,
       textColor=TINTA, spaceBefore=6, spaceAfter=3)
KICKER = S("KICKER", fontName="Helvetica-Bold", fontSize=7.6, leading=11,
           textColor=VERDE, spaceAfter=2)
H2 = S("H2", fontName="Helvetica-Bold", fontSize=12.4, leading=16.5,
       spaceBefore=13, spaceAfter=4)
SMALL = S("SMALL", fontSize=8.8, leading=12.6, textColor=SUAVE)
MONO = S("MONO", fontName="Courier", fontSize=8.6, leading=12.6)
CENTER = S("CENTER", alignment=TA_CENTER)


def caja(texto, fondo, borde, tinta=TINTA, style=None):
    st = style or S("cx", textColor=tinta, spaceAfter=0)
    t = Table([[Paragraph(texto, st)]], colWidths=[165 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fondo),
        ("BOX", (0, 0), (-1, -1), 0.9, borde),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def clave(texto):
    return caja(texto, VERDE_SUAVE, VERDE)


def ojo(texto):
    return caja("<b>Ojo:</b> " + texto, AMBAR, AMBAR_LIN, AMBAR_TXT)


def tabla(data, anchos, destacar=None, mono_cols=()):
    t = Table(data, colWidths=anchos, hAlign="LEFT")
    estilo = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), SUAVE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF1EA")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINEA),
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]
    for c in mono_cols:
        estilo.append(("FONTNAME", (c, 1), (c, -1), "Courier"))
    if destacar is not None:
        estilo += [("BACKGROUND", (0, destacar), (-1, destacar), VERDE_SUAVE),
                   ("FONTNAME", (0, destacar), (-1, destacar), "Helvetica-Bold")]
    t.setStyle(TableStyle(estilo))
    return t


def pie(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINEA)
    canvas.setLineWidth(0.5)
    canvas.line(22 * mm, 15 * mm, 188 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(SUAVE)
    canvas.drawString(22 * mm, 10.5 * mm, "marcador-futbol · guía rápida")
    canvas.drawRightString(188 * mm, 10.5 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def diagrama_ciclo():
    """El ciclo en cuatro cajas, dibujado con una tabla."""
    pasos = [
        ("1", "Predice", "Antes del partido.\nSe guarda y no se toca."),
        ("2", "Espera", "Se juega.\nNadie interviene."),
        ("3", "Mide", "Compara lo dicho\ncon lo que pasó."),
        ("4", "Decide", "Cambia de modelo\nsolo si gana claro."),
    ]
    fila_n, fila_t, fila_d = [], [], []
    for n, t, d in pasos:
        fila_n.append(Paragraph(f"<b>{n}</b>", S("n", fontSize=15,
                                                 textColor=VERDE,
                                                 alignment=TA_CENTER)))
        fila_t.append(Paragraph(f"<b>{t}</b>", S("t", fontSize=11,
                                                 alignment=TA_CENTER)))
        fila_d.append(Paragraph(d.replace("\n", "<br/>"),
                                S("d", fontSize=8.4, leading=11.6,
                                  textColor=SUAVE, alignment=TA_CENTER)))
    t = Table([fila_n, fila_t, fila_d], colWidths=[41 * mm] * 4, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                          leftMargin=22 * mm, rightMargin=22 * mm,
                          topMargin=20 * mm, bottomMargin=20 * mm,
                          title="marcador-futbol — guía rápida",
                          author="marcador-futbol")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="n")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=pie)])
    s = []
    a = s.append

    # ---------------- PORTADA ----------------
    a(Spacer(1, 42 * mm))
    a(Paragraph("GUÍA RÁPIDA", KICKER))
    a(Paragraph("Marcador antes que modelo", S("tit", fontName="Helvetica-Bold",
                                               fontSize=30, leading=34)))
    a(Spacer(1, 5))
    a(Paragraph("Cómo funciona un modelo de fútbol que se califica solo, "
                "y cómo leer su tablero. Sin matemáticas.", LEAD))
    a(Spacer(1, 8 * mm))
    a(clave("<b>Lee esto si:</b> quieres entender qué hace el sistema y cómo "
            "usarlo, pero no vas a leer la documentación del repositorio. "
            "Son diez minutos."))
    a(Spacer(1, 8 * mm))
    a(Paragraph("Tablero en vivo", S("x", fontName="Helvetica-Bold",
                                     fontSize=9, spaceAfter=1)))
    a(Paragraph("marcador-futbol-2rs4efqkkrvipztze7k5mr.streamlit.app", MONO))
    a(Spacer(1, 4))
    a(Paragraph("Código y documentación completa", S("y", fontName="Helvetica-Bold",
                                                     fontSize=9, spaceAfter=1)))
    a(Paragraph(REPO, MONO))
    a(PageBreak())

    # ---------------- 1 ----------------
    a(Paragraph("01", KICKER))
    a(Paragraph("Qué es esto, en 30 segundos", H1))
    a(Paragraph("Un sistema que predice resultados de fútbol en las cinco "
                "grandes ligas europeas y <b>se pone nota a sí mismo</b>. "
                "Escribe lo que cree que va a pasar antes de cada partido, "
                "guarda esa predicción donde ya no puede tocarla, espera el "
                "resultado y calcula qué tan bien lo hizo.", P))
    a(Spacer(1, 6))
    a(diagrama_ciclo())
    a(Spacer(1, 10))
    a(Paragraph("La idea que lo ordena todo", H2))
    a(Paragraph("Lo normal sería empezar por el modelo. Aquí se empezó por el "
                "<b>marcador</b>: primero se construyó la forma de juzgar "
                "predicciones y solo después se hizo algo que predijera. "
                "El primer «modelo» del proyecto fue deliberadamente tonto —"
                "decir siempre el promedio histórico— y sirvió para comprobar "
                "que el sistema de medición funcionaba.", P))
    a(clave("Un modelo que «se corrige solo» necesita saber <b>en qué "
            "dirección</b> corregirse. Eso solo lo da un sistema de medición "
            "que ya existía antes que el modelo."))
    a(Spacer(1, 10))
    a(Paragraph("Los números de hoy", H2))
    a(tabla([
        ["", "Qué tan bien predice", "Lectura"],
        ["Decir el promedio", "1.068", "El piso. Sin esto no hay modelo."],
        ["Un rating simple (Elo)", "0.985", "Sorprendentemente difícil de batir."],
        ["Este modelo", "0.979", "Empate con ventaja sobre Elo."],
        ["Las casas de apuestas", "0.956", "El techo. Todavía mandan ellas."],
    ], [46 * mm, 38 * mm, 81 * mm], destacar=3, mono_cols=(1,)))
    a(Spacer(1, 5))
    a(Paragraph("Menos es mejor. La columna se llama <i>log-loss</i> y la "
                "explicamos en la página 5.", SMALL))
    a(PageBreak())

    # ---------------- 2 ----------------
    a(Paragraph("02", KICKER))
    a(Paragraph("Cómo funciona el modelo", H1))
    a(Paragraph("Sin una sola fórmula. El modelo no intenta adivinar quién "
                "gana: intenta estimar <b>cuántos goles marca cada equipo</b>, "
                "y de ahí sale todo lo demás.", LEAD))
    a(Paragraph("Cada equipo tiene dos notas", H2))
    a(tabla([
        ["Nota", "Qué mide", "Ejemplo"],
        ["Ataque", "Cuanto marca por encima o por debajo del promedio",
         "Un equipo con +0.30 marca ~35% más que el promedio"],
        ["Defensa", "Cuanto le marcan por encima o por debajo del promedio",
         "Negativo es bueno: encaja menos de lo normal"],
    ], [26 * mm, 63 * mm, 76 * mm]))
    a(Spacer(1, 5))
    a(Paragraph("Y la liga entera tiene una tercera: <b>la ventaja de jugar en "
                "casa</b>. Con esas tres cosas el modelo estima cuántos goles "
                "espera de cada lado.", P))
    a(Spacer(1, 4))
    a(Paragraph("En Excel sería una tabla con dos columnas por equipo, una "
                "celda con la ventaja de local, y una formula que combina la "
                "fila del local con la del visitante. Ajustar el modelo es "
                "buscar los valores de esas columnas que mejor explican los "
                "marcadores que de verdad ocurrieron.", P))
    a(Spacer(1, 8))
    a(Paragraph("De los goles esperados a las probabilidades", H2))
    a(Paragraph("Supongamos que el modelo espera 1.9 goles del local y 0.9 del "
                "visitante. Con eso arma una tabla con la probabilidad de cada "
                "marcador posible:", P))
    a(Spacer(1, 3))
    a(tabla([
        ["", "0 del visitante", "1", "2", "3+"],
        ["0 del local", "6%", "5%", "2%", "1%"],
        ["1", "11%", "10%", "5%", "2%"],
        ["2", "11%", "10%", "4%", "2%"],
        ["3+", "12%", "10%", "5%", "4%"],
    ], [33 * mm, 33 * mm, 33 * mm, 33 * mm, 33 * mm], mono_cols=(1, 2, 3, 4)))
    a(Spacer(1, 5))
    a(Paragraph("Sumando las casillas correspondientes salen todos los "
                "mercados a la vez: la diagonal es el empate, lo de abajo es "
                "victoria local, lo de arriba victoria visitante, y las "
                "casillas donde los goles suman más de 2 son el «over 2.5».", P))
    a(clave("Esa tabla es la razón de que el sistema pueda predecir corners, "
            "tarjetas o tiros con el <b>mismo código</b>: solo cambia qué "
            "está contando. El motor no sabe si cuenta goles o corners."))
    a(Spacer(1, 6))
    a(Paragraph("(Los porcentajes del ejemplo son ilustrativos y están "
                "redondeados.)", SMALL))
    a(PageBreak())

    # ---------------- 3 ----------------
    a(Paragraph("03", KICKER))
    a(Paragraph("Las tres cosas que lo hacen distinto", H1))
    a(Paragraph("Cualquiera puede entrenar un modelo de fútbol. Lo que "
                "distingue a este son tres reglas que están <b>impuestas por "
                "el sistema</b>, no confiadas a la buena voluntad de quien "
                "programa.", LEAD))
    a(Paragraph("1. Olvida el pasado a propósito", H2))
    a(Paragraph("Un partido de hace cinco años no dice casi nada del equipo de "
                "hoy. El modelo le da menos peso a los partidos viejos: uno de "
                "hace un año pesa la mitad que uno de esta semana.", P))
    a(Paragraph("Resultó ser <b>casi toda la ventaja del modelo</b>. Sin "
                "olvidar, es peor que un rating Elo de veinte lineas.", P))
    a(Paragraph("2. No puede hacer trampa", H2))
    a(Paragraph("El error clásico en estos proyectos es usar sin darse cuenta "
                "información que en su momento no existía: la tabla final de "
                "la temporada, la forma calculada con partidos que aún no se "
                "habían jugado. El síntoma es que todo sale increíble en las "
                "pruebas y se derrumba en vivo.", P))
    a(Paragraph("Aquí la base de datos <b>rechaza</b> cualquier predicción "
                "cuyo corte de información sea posterior al partido, y rechaza "
                "cualquier intento de modificar o borrar una predicción ya "
                "escrita. No es una advertencia en un documento: la escritura "
                "falla.", P))
    a(Paragraph("3. No puede empeorar", H2))
    a(Paragraph("Cada semana el sistema busca una versión nueva de sí mismo y "
                "la enfrenta a la que está en producción, sobre partidos que "
                "ninguna de las dos vio. <b>La nueva solo entra si gana de "
                "forma clara.</b> Un empate lo gana la que ya estaba.", P))
    a(Spacer(1, 3))
    a(ojo("Esto no es exceso de prudencia. En una versión temprana el propio "
          "proyecto anunció que «le ganaba a Elo» por una diferencia que "
          "resultó ser puro azar. Si el sistema promoviera con cada golpe de "
          "suerte, se iría degradando a punta de mejoras imaginarias."))
    a(Spacer(1, 8))
    a(Paragraph("Cómo va ese historial", H2))
    a(tabla([
        ["Desafíos al modelo en producción", "Resultado"],
        ["Ajuste distinto de los parametros", "Rechazado"],
        ["El mismo ajuste, otra vez", "Rechazado"],
        ["Capa nueva, probada con una sola liga", "Rechazado"],
        ["La misma capa, probada con cinco ligas", "PROMOVIDO"],
    ], [110 * mm, 55 * mm], destacar=4))
    a(Spacer(1, 5))
    a(Paragraph("Tres rechazos y una promoción. Los rechazos se guardan "
                "justamente porque son la prueba de que el filtro existe.", SMALL))
    a(PageBreak())

    # ---------------- 4 ----------------
    a(Paragraph("04", KICKER))
    a(Paragraph("Cómo leer el tablero", H1))
    a(Paragraph("El tablero está en la dirección de la portada. Se abre en el "
                "navegador, no hay que instalar nada, y todo lo que muestra "
                "sale de archivos públicos del repositorio: cualquiera puede "
                "comprobar los números.", LEAD))

    secciones = [
        ("Campeón y desafíos",
         "Qué versión está prediciendo hoy y desde cuándo. Debajo, la lista de "
         "todos los intentos de reemplazarla, aprobados y rechazados. La "
         "columna <i>veredicto</i> es lo que decidió el filtro; la columna "
         "<i>p</i> es qué tan seguro se puede estar de la diferencia: por "
         "debajo de 0.05 se considera sólida."),
        ("Dónde pierde contra el mercado",
         "El sistema se compara con las casas de apuestas, que son la "
         "referencia más exigente que existe. Esta sección parte esa "
         "diferencia por tipo de partido. La columna <i>brecha</i> es cuánto "
         "peor lo hace en ese grupo; la columna <i>aporta</i> es cuánto de la "
         "diferencia total viene de ahí. <b>El grupo que hay que mirar es el "
         "que más aporta</b>, no el de mayor brecha: un grupo con brecha "
         "enorme pero cuatro partidos no mueve nada."),
        ("Próximos partidos",
         "Las predicciones ya emitidas para partidos que aún no se juegan, con "
         "las tres probabilidades. Suman 100%. Si está vacío no es un error: "
         "la fuente de datos publica los próximos partidos con solo unos días "
         "de antelación."),
        ("Partidos ya jugados",
         "Lo mismo, pero con el resultado al lado y la probabilidad que el "
         "modelo le había dado. Es la forma más directa de ver si acierta."),
        ("Calibración",
         "El gráfico más útil y el menos obvio. Agrupa las predicciones por "
         "el porcentaje que se dio y compara con lo que de verdad pasó. Si el "
         "modelo dice 70% y pasa 7 de cada 10 veces, está calibrado y los "
         "puntos caen sobre la diagonal."),
        ("Otros mercados",
         "Corners, tarjetas y tiros a puerta. La columna <i>w</i> es cuanto se "
         "le cree al modelo frente a simplemente decir el promedio: un valor "
         "bajo significa que en ese mercado la señal es débil."),
    ]
    for titulo, texto in secciones:
        a(KeepTogether([Paragraph(titulo, H2), Paragraph(texto, P)]))
    a(Spacer(1, 4))
    a(ojo("Cuando el tablero avisa de que hay pocos partidos, hazle caso. Un "
          "log-loss calculado con veinte partidos se mueve muchísimo y no "
          "significa nada; hacen falta unos cien para que el número se "
          "estabilice."))
    a(PageBreak())

    # ---------------- 5 ----------------
    a(Paragraph("05", KICKER))
    a(Paragraph("Los números, en cristiano", H1))
    a(Paragraph("Log-loss: la nota principal", H2))
    a(Paragraph("Es el número que decide todo en este proyecto. Mide qué "
                "probabilidad le diste al resultado que de verdad ocurrió, y "
                "<b>castiga muchísimo la confianza equivocada</b>.", P))
    a(Spacer(1, 3))
    a(tabla([
        ["Dijiste que pasaría con…", "Y pasó", "Cuánto suma a tu nota"],
        ["70% de probabilidad", "sí", "0.36  (bien)"],
        ["50%", "sí", "0.69"],
        ["10%", "sí", "2.30  (mal)"],
        ["2%", "sí", "3.91  (desastre)"],
    ], [56 * mm, 30 * mm, 79 * mm], mono_cols=(2,)))
    a(Spacer(1, 5))
    a(Paragraph("Esa asimetría es el punto. Un modelo que casi nunca se "
                "equivoca pero que cuando lo hace estaba segurísimo es un "
                "modelo peligroso, y log-loss lo detecta donde el simple "
                "porcentaje de aciertos no.", P))
    a(Spacer(1, 3))
    a(Paragraph("Menos es mejor. Alrededor de 1.07 es «no sé nada»; 0.96 es lo "
                "que consiguen las casas de apuestas.", P))
    a(Spacer(1, 8))
    a(Paragraph("Por qué el porcentaje de aciertos no sirve", H2))
    a(Paragraph("Parece la medida obvia y es engañosa. En este proyecto el "
                "modelo final <b>acierta menos partidos que Elo</b> (53.2% "
                "contra 54.3%) y aun así es mejor, porque sus probabilidades "
                "son más honestas.", P))
    a(Paragraph("La razón: acertar no es el objetivo. Si dices 55% para el "
                "local en todos los partidos, aciertas mucho y no has dicho "
                "nada útil. Lo que importa es que cuando dices 70%, pase el "
                "70% de las veces.", P))
    a(clave("Por eso el tablero muestra el porcentaje de aciertos como dato "
            "de contexto y <b>no decide nada con el</b>."))
    a(Spacer(1, 8))
    a(Paragraph("La calibración", H2))
    a(Paragraph("Es la pregunta «¿cuando dices 70%, pasa 7 de cada 10 veces?». "
                "Un modelo puede tener buena nota y estar mal calibrado: ser "
                "sistemáticamente exagerado o tímido. El gráfico agrupa las "
                "predicciones por el porcentaje que se dio y compara con la "
                "realidad. La diagonal es la perfección.", P))
    a(Paragraph("De los dos defectos, el exagerado es el grave: su error crece "
                "justo donde uno más confiaría en él.", P))
    a(PageBreak())

    # ---------------- 6 ----------------
    a(Paragraph("06", KICKER))
    a(Paragraph("Qué NO hace este sistema", H1))
    a(Paragraph("Esta página importa tanto como las anteriores. Un proyecto "
                "que solo cuenta lo que le sale bien es un folleto.", LEAD))
    a(Paragraph("No le gana al mercado", H2))
    a(Paragraph("Las casas de apuestas predicen mejor, y la diferencia es "
                "clara, no discutible. Se simuló apostar según el modelo sobre "
                "cinco temporadas: el resultado fue <b>perder un 8.5%</b> de lo "
                "apostado. Y lo más revelador: apostar a todos los partidos sin "
                "criterio pierde menos (6%). El filtro del modelo elige justo "
                "los partidos donde más discrepa del precio, y ahí el mercado "
                "tiene razon.", P))
    a(Spacer(1, 3))
    a(ojo("Este documento describe un ejercicio de análisis. No es una "
          "recomendación de apuesta ni un consejo financiero, y el propio "
          "sistema muestra que usarlo para apostar habría dado pérdidas."))
    a(Paragraph("No predice bien todos los mercados", H2))
    a(Paragraph("De cuatro mercados construidos sobre el mismo motor, "
                "<b>solo uno</b> —las tarjetas— le gana de forma demostrable a "
                "decir simplemente el promedio. Corners, goles over/under y "
                "tiros dan mejoras positivas pero indistinguibles del azar.", P))
    a(Paragraph("No tiene historial en vivo todavía", H2))
    a(Paragraph("Todo lo que reporta viene de simulaciones sobre partidos "
                "pasados, hechas con reglas estrictas para que sean honestas. "
                "El sistema está construido y verificado, pero aún no ha "
                "acumulado predicciones sobre partidos futuros. Hasta que "
                "tenga unas cien, conviene leer los números como lo que son.", P))
    a(Paragraph("No sabe de lesiones, alineaciones ni motivacion", H2))
    a(Paragraph("Solo ve goles, tiros, corners y tarjetas de partidos "
                "anteriores. El mercado ve todo lo demás, y buena parte de su "
                "ventaja viene de ahí.", P))
    a(Spacer(1, 6))
    a(clave("Que el sistema diga estas cosas de sí mismo no es modestia: es "
            "el mismo mecanismo que le impide promover mejoras imaginarias. "
            "Un proyecto que mide en serio produce esta lista sin querer."))
    a(PageBreak())

    # ---------------- 7 ----------------
    a(Paragraph("07", KICKER))
    a(Paragraph("Correrlo tú mismo", H1))
    a(Paragraph("Opcional. El tablero no exige nada de esto: se abre en el "
                "navegador. Esto es para quien quiera reproducir los números "
                "en su máquina. Hace falta Python 3.11 o superior.", LEAD))
    a(Paragraph("Preparar", H2))
    a(Paragraph(f"git clone https://{REPO}<br/>"
                "cd marcador-futbol<br/>"
                "python3 -m venv .venv<br/>"
                "./.venv/bin/pip install -r requirements.txt", MONO))
    a(Spacer(1, 8))
    a(Paragraph("Bajar los datos y ver el marcador", H2))
    a(Paragraph("./.venv/bin/python scripts/01_ingest.py<br/>"
                "./.venv/bin/python scripts/02_baseline.py", MONO))
    a(Paragraph("El primero baja unas 20.000 filas de partidos de las cinco "
                "ligas. El segundo calcula las referencias contra las que se "
                "juzga todo.", SMALL))
    a(Spacer(1, 8))
    a(Paragraph("Ver el modelo y su prueba completa", H2))
    a(Paragraph("./.venv/bin/python scripts/03_dixon_coles.py", MONO))
    a(Paragraph("Tarda un par de minutos. Imprime cuánto aporta cada pieza del "
                "modelo y si esa aportación es sólida o es ruido.", SMALL))
    a(Spacer(1, 8))
    a(Paragraph("Ver qué decidiría el filtro hoy", H2))
    a(Paragraph("./.venv/bin/python scripts/06_retrain.py --dry-run", MONO))
    a(Paragraph("Busca una versión nueva, la enfrenta a la actual y dice si la "
                "promovería. Con --dry-run no escribe nada.", SMALL))
    a(Spacer(1, 8))
    a(Paragraph("Abrir el tablero en local", H2))
    a(Paragraph("./.venv/bin/streamlit run dashboard/app.py", MONO))
    a(Spacer(1, 12))
    a(Paragraph("Si algo no cuadra", H2))
    a(tabla([
        ["Síntoma", "Qué suele ser"],
        ["No baja datos", "La fuente rechaza el subdominio con www. El código "
                          "ya usa el dominio sin el."],
        ["El tablero sale vacío", "Todavía no hay predicciones en vivo. Las "
                                  "secciones de arriba sí deberían verse."],
        ["Un número no coincide", "Los datos de la temporada en curso cambian "
                                  "cada semana."],
    ], [48 * mm, 117 * mm]))
    a(Spacer(1, 12))
    a(caja("La documentación completa —incluida la lista de todo lo que no "
           "funcionó y por qué— está en el repositorio, en "
           "<font face='Courier'>APRENDIZAJES.md</font>. Este PDF es el "
           "resumen; ese archivo es la versión larga y honesta.",
           colors.HexColor("#EDF1EA"), LINEA))

    doc.build(s)
    print(f"  {OUT.relative_to(Path.cwd())} generado")


if __name__ == "__main__":
    build()
