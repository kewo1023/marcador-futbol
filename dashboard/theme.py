"""Identidad visual del dashboard: jerarquia tipografica, logo y marca de agua.

La otra mitad esta en .streamlit/config.toml (fuentes, escala de titulos,
colores de los dos modos). Aqui va lo que el tema de Streamlit no alcanza.

Un cambio aqui pide Reboot app igual que uno en src/ (regla 9): el proceso
conserva el modulo viejo en memoria. Por eso app.py solo usa tres nombres
—FAVICON, apply() y watermark()— y no cambian: con el modulo viejo, el
dashboard se ve con el estilo anterior en vez de romperse.

LAS REGLAS DE JERARQUIA. Cinco pasos de tamaño, y cada elemento del tablero
cae en uno solo:

    28/34  Space Grotesk 600   titulo de pagina (st.title) y valor de metrica
                               (este en Inter 600: es un dato, no un titulo)
    20/26  Space Grotesk 600   seccion (st.subheader), con filete y aire arriba
    16/24  Space Grotesk 500   bloque dentro de una seccion ("#### ...")
    16/24  Inter 400           cuerpo, avisos
    14/20  Inter 400           explicacion (st.caption), en texto secundario
    14/20  Space Grotesk 500   etiqueta de metrica, en texto secundario
    12/16  —                   reservado; solo lo usa la marca de agua

Lo que separa niveles es el tamaño y el aire, nunca el color: el texto
secundario es para lo que se lee despues, no para lo que importa menos.
Una seccion nueva lleva st.subheader; un titulo hecho con "**negrita**"
no entra en la jerarquia y se pierde al escanear la pagina.

Los colores salen de TOKENS y se resuelven con light-dark(): Streamlit marca
color-scheme en la raiz de la app, asi que el modo lo decide el mismo tema
que pinta el resto, sin leer st.context (que puede mentir en la primera
carga).
"""
import streamlit as st

BRAND = "Karf Studio"

# (claro, oscuro). Los mismos valores que config.toml.
TOKENS = {
    "text": ("#0F172A", "#F8FAFC"),
    "text-secondary": ("#475569", "#CBD5E1"),
    "border": ("#E2E8F0", "#334155"),
    # Marca de agua: texto secundario al 40 % en claro y al 45 % en oscuro.
    # El tope del spec es 60 %.
    "watermark": ("rgb(71 85 105 / 0.40)", "rgb(203 213 225 / 0.45)"),
}

# El simbolo: 3 trazos a 24 px o mas; silueta solida por debajo, porque a
# ese tamaño los cortes se cierran.
MARK = ('<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true">'
        '<rect x="5" y="4" width="6" height="24" fill="currentColor"/>'
        '<path d="M13.5 8.6 L19.4 4 L27.5 4 L13.5 15 Z" fill="currentColor"/>'
        '<path d="M13.5 23.4 L19.4 28 L27.5 28 L13.5 17 Z" fill="currentColor"/>'
        '</svg>')
MARK_SOLID = ('<svg viewBox="0 0 32 32" width="{s}" height="{s}" aria-hidden="true">'
              '<path d="M5 4 H11 V10.6 L19.4 4 H27.5 L12.2 16 L27.5 28 H19.4 '
              'L11 21.4 V28 H5 Z" fill="currentColor"/></svg>')

# La pestaña del navegador no hereda currentColor: el favicon trae su color,
# y el del modo oscuro por media query.
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<path d="M5 4 H11 V10.6 L19.4 4 H27.5 L12.2 16 L27.5 28 H19.4 '
           'L11 21.4 V28 H5 Z" fill="#2563EB"/>'
           '<style>@media (prefers-color-scheme: dark) '
           '{ path { fill: #3B82F6; } }</style></svg>')

_VARS = "\n".join(f"  --brand-{k}: light-dark({lt}, {dk});"
                  for k, (lt, dk) in TOKENS.items())

CSS = f"""<style>
.stApp {{
{_VARS}
  --brand-display: 'Space Grotesk', sans-serif;
}}

/* Cuerpo: 16/24, y una linea de lectura que no cruce la pantalla entera. */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {{ line-height: 24px; }}
[data-testid="stMarkdownContainer"] p {{ max-width: 75ch; }}

/* Titulo de pagina: 28/34. */
[data-testid="stHeading"] h1 {{ line-height: 34px; padding: 0 0 4px; }}

/* Seccion: 20/26, con filete arriba. El aire de antes (48 px) es el doble
   del que separa los bloques dentro de una seccion: asi se ve donde empieza
   cada una sin leer nada. */
.stElementContainer:has(> [data-testid="stHeading"] h3) {{
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--brand-border);
}}
[data-testid="stHeading"] h3 {{ line-height: 26px; padding: 0; }}

/* Bloque dentro de una seccion: 16/24, Space Grotesk 500. */
.stElementContainer:has(> [data-testid="stHeading"] h4),
.stElementContainer:has(> div > [data-testid="stMarkdown"] h4) {{ margin-top: 8px; }}
[data-testid="stHeading"] h4,
[data-testid="stMarkdownContainer"] h4 {{
  line-height: 24px;
  padding: 0;
}}

/* Explicacion: 14/20 en texto secundario. Es lo mas abundante del tablero,
   y por eso es lo que mas tiene que apartarse de los datos. */
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {{
  font-size: 14px;
  line-height: 20px;
  color: var(--brand-text-secondary);
  max-width: 75ch;
}}
[data-testid="stCaptionContainer"] strong {{ color: var(--brand-text); }}

/* Metrica: etiqueta 14/20 Space Grotesk 500 en secundario; valor 28/34
   Inter 600 (el tamaño y el peso vienen del config.toml). Cifras tabulares
   para que los numeros de columnas vecinas se alineen. */
[data-testid="stMetricLabel"] p {{
  font-family: var(--brand-display);
  font-weight: 500;
  font-size: 14px;
  line-height: 20px;
  color: var(--brand-text-secondary);
}}
[data-testid="stMetricValue"] {{
  line-height: 34px;
  font-variant-numeric: tabular-nums;
}}
[data-testid="stMetricDelta"] {{
  font-size: 14px;
  line-height: 20px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}}

/* Lockup horizontal: simbolo a 24 px + nombre, separacion 12 px. */
.brand-lockup {{
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--brand-text);
  font-family: var(--brand-display);
  font-weight: 600;
  font-size: 16px;
  line-height: 24px;
}}
.brand-lockup svg {{ display: block; flex: none; }}
.stElementContainer:has(.brand-lockup) {{ margin-bottom: 16px; }}

/* Marca de agua: abajo a la izquierda, al final de la pagina y no fija.
   Fija pasaria por encima de las tablas al hacer scroll, y la regla es que
   nunca va sobre contenido interactivo. */
.brand-watermark {{
  display: flex;
  align-items: center;
  gap: 12px;
  width: max-content;
  margin-top: 48px;
  padding: 8px;
  color: var(--brand-watermark);
  pointer-events: none;
  user-select: none;
}}
.brand-watermark svg {{ display: block; width: 16px; height: 16px; }}
.brand-watermark span {{
  font-family: var(--brand-display);
  font-weight: 500;
  font-size: 12px;
  line-height: 12px;
}}
</style>"""


def apply():
    """Estilos y logo. Va justo despues de st.set_page_config."""
    st.html(CSS)
    # st.markdown y no st.html: st.html sanitiza y se come el <svg>.
    st.markdown(f'<div class="brand-lockup" role="img" aria-label="{BRAND}">'
                f'{MARK.format(s=24)}<span aria-hidden="true">{BRAND}</span></div>',
                unsafe_allow_html=True)


def watermark():
    """La marca de agua. Va al final de la pagina, y antes de cualquier
    st.stop() que corte el tablero antes de llegar ahi."""
    st.markdown(f'<div class="brand-watermark" aria-hidden="true">'
                f'{MARK_SOLID.format(s=16)}<span>{BRAND}</span></div>',
                unsafe_allow_html=True)
