"""EcomAnalysis Design System — tema enterprise light (bianco/grigio con accento teal) + componenti UI.

Unico punto di verità per l'aspetto dell'app. Ogni pagina Streamlit chiama
`page_setup()` come PRIMA cosa (sostituisce st.set_page_config + st.title) e
usa i componenti qui sotto (metric_cards, section, data_table, style_fig).
"""
from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Token — palette ufficiale Light Enterprise (bianco/grigio con accento teal)
# ---------------------------------------------------------------------------
LIGHT = {
    "bg": "#F1F5F9",            # fondo app (grigio chiaro enterprise / slate-100)
    "surface": "#FFFFFF",       # pannelli / sidebar / card (bianco puro)
    "card": "#FFFFFF",          # card KPI
    "card_hover": "#F0FDF9",    # hover card (tocco leggero teal)
    "border": "#CBD5E1",        # bordi definiti e visibili (slate-300)
    "border_subtle": "#E2E8F0", # bordi divisori interni secondari
    "text": "#0F1B2D",          # testo primario (slate navy scuro ad alto contrasto)
    "muted": "#5B6B82",         # testo secondario / label / caption
    "accent": "#0D9488",        # teal brand
    "accent_hover": "#0F766E",  # teal scuro hover
    "accent_soft": "rgba(13, 148, 136, 0.10)",
    "positive": "#059669",
    "negative": "#DC2626",
    "warning": "#D97706",
    "grid": "rgba(15, 27, 45, 0.08)",
    "font": "'Inter', 'Segoe UI', system-ui, sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, monospace",
}

# Retrocompatibilità se qualche import interno fa riferimento a DARK
DARK = LIGHT

# Palette serie (grafici): accent teal sempre primo, poi blu/neutri coerenti.
SERIES = ["#0D9488", "#3B82F6", "#F59E0B", "#8B5CF6", "#64748B", "#EC4899"]


def _t() -> dict:
    return LIGHT


# ---------------------------------------------------------------------------
# Tema — modalità corrente, persistenza, CSS
# ---------------------------------------------------------------------------
def theme_mode() -> str:
    """Sempre 'light' (tema unico aziendale)."""
    st.session_state["ds_theme"] = "light"
    return "light"


def set_theme(mode: str) -> None:
    """Mantenuta per retrocompatibilità: imposta sempre 'light'."""
    st.session_state["ds_theme"] = "light"
    if "theme" in st.query_params:
        try:
            del st.query_params["theme"]
        except Exception:
            pass


def _css() -> str:
    t = LIGHT
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root, html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMainBlockContainer"], .main {{
    --background: {t["bg"]};
    --secondary-background-color: {t["surface"]};
    --background-color: {t["bg"]};
    --text-color: {t["text"]};
    --secondary-text-color: {t["muted"]};
    --primary-color: {t["accent"]};
    --font: {t["font"]};
    background-color: {t["bg"]};
    color: {t["text"]};
    font-family: {t["font"]};
}}

/* Header Streamlit trasparente e non bloccante */
header[data-testid="stHeader"] {{
    background: transparent !important;
    pointer-events: none;
}}
header[data-testid="stHeader"] * {{
    pointer-events: auto;
}}

/* Spaziatura superiore ottimizzata: compatta su tutte le pagine senza topbar */
.block-container, [data-testid="stMainBlockContainer"] {{
    padding-top: 1.25rem !important;
    padding-bottom: 2.5rem !important;
}}

/* Riserva lo spazio superiore solo per pagine con la topbar (Analisi Dati) */
.block-container:has(.st-key-topbar),
[data-testid="stMainBlockContainer"]:has(.st-key-topbar) {{
    padding-top: 3.25rem !important;
}}

/* Assicura che testo e paragrafi siano sempre scuri su chiaro e perfettamente leggibili */
p, span, label, li, [data-testid="stText"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {{
    color: {t["text"]};
    font-family: {t["font"]};
}}

h1, h2, h3, h4, h5, h6,
[data-testid="stHeadingWithActionElements"] h1,
[data-testid="stHeadingWithActionElements"] h2,
[data-testid="stHeadingWithActionElements"] h3 {{
    color: {t["text"]} !important;
    font-family: {t["font"]};
}}

/* Link */
a {{
    color: {t["accent"]};
    text-decoration: none;
}}
a:hover {{
    color: {t["accent_hover"]};
    text-decoration: underline;
}}

/* Didascalie / testo secondario */
.stCaption, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, [data-testid="stCaptionContainer"] span {{
    color: {t["muted"]} !important;
}}

/* Divisori orizzontali */
hr {{
    border-color: {t["border"]} !important;
}}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background-color: {t["surface"]} !important;
    border-right: 1px solid {t["border"]} !important;
}}
[data-testid="stSidebar"] * {{ font-family: {t["font"]}; }}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {{
    color: {t["text"]};
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    font-size: .95rem; font-weight: 700; letter-spacing: .02em; color: {t["text"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
    border-radius: 8px;
    padding: 6px 10px;
    transition: background .15s ease, color .15s ease;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] span,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p {{
    color: {t["text"]} !important;
    font-size: .88rem;
    font-weight: 500;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{
    background-color: {t["card_hover"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover span,
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover p {{
    color: {t["accent"]} !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: {t["surface"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: 8px !important;
    margin-bottom: 6px;
    box-shadow: 0 1px 2px rgba(15, 27, 45, 0.03);
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span {{
    color: {t["text"]} !important;
    font-size: .88rem;
    font-weight: 600;
}}

/* Icone Streamlit ligature */
[data-testid="stIconMaterial"], [data-testid="stSidebar"] [data-testid="stIconMaterial"],
span[class*="material-icons"], span[class*="material-symbols"] {{
    font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
    font-weight: 400 !important; font-style: normal !important;
    text-transform: none !important; letter-spacing: normal !important;
    white-space: nowrap !important;
    font-feature-settings: "liga" !important;
}}

/* ---------- Header pagina ---------- */
.ds-header {{
    display: flex; align-items: center; gap: 14px;
    padding: 10px 4px 6px 0; margin-bottom: 8px;
    border-bottom: 1px solid {t["border"]};
}}
.ds-header .ds-icon {{
    width: 46px; height: 46px; border-radius: 12px; flex: 0 0 auto;
    background: {t["accent_soft"]};
    display: flex; align-items: center; justify-content: center; font-size: 24px;
    border: 1px solid rgba(13, 148, 136, 0.20);
}}
.ds-header h1 {{
    font-size: 1.55rem; font-weight: 800; letter-spacing: -0.01em;
    margin: 0; color: {t["text"]}; line-height: 1.2;
}}
.ds-header .ds-sub {{ font-size: .85rem; color: {t["muted"]}; margin: 2px 0 0; }}

/* ---------- Sezioni ---------- */
.ds-section {{ display: flex; align-items: baseline; gap: 10px; margin: 26px 0 4px; }}
.ds-section h2 {{
    font-size: 1.05rem; font-weight: 700; margin: 0; color: {t["text"]};
    letter-spacing: .01em;
}}
.ds-section .ds-bar {{
    width: 4px; height: 18px; border-radius: 2px; background: {t["accent"]};
    align-self: center; flex: 0 0 auto;
}}
.ds-caption {{ color: {t["muted"]}; font-size: .8rem; margin: 2px 0 10px; }}

/* ---------- Card KPI ---------- */
.ds-cards {{
    display: grid; gap: 12px; margin: 10px 0 6px;
    grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
}}
.ds-card {{
    min-width: 0; overflow: hidden; background: {t["card"]};
    border: 1px solid {t["border"]}; border-radius: 12px;
    padding: 12px 14px 10px;
    box-shadow: 0 1px 3px rgba(15, 27, 45, 0.07), 0 1px 2px rgba(15, 27, 45, 0.04);
    transition: background .15s ease, border-color .15s ease, box-shadow .15s ease;
}}
.ds-card:hover {{
    background: {t["card_hover"]};
    border-color: {t["accent"]};
    box-shadow: 0 4px 12px rgba(13, 148, 136, 0.12);
}}
.ds-card .ds-label {{
    font-size: .72rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .06em; color: {t["muted"]}; margin: 0 0 6px;
    line-height: 1.3; min-height: 2.6em;
    white-space: normal; overflow-wrap: break-word;
}}
.ds-card .ds-value {{
    font-size: clamp(1.02rem, 1.1vw + .32rem, 1.32rem); font-weight: 800; color: {t["text"]};
    font-variant-numeric: tabular-nums; margin: 0; line-height: 1.25;
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: -0.02em;
}}
.ds-card .ds-delta {{
    font-size: .8rem; font-weight: 600; margin: 4px 0 0;
    white-space: nowrap !important;
}}

/* ---------- Tabelle & Dataframe ---------- */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    border: 1px solid {t["border"]} !important;
    border-radius: 12px !important;
    overflow: hidden;
    background: {t["surface"]} !important;
    box-shadow: 0 1px 4px rgba(15, 27, 45, 0.06) !important;
}}
[data-testid="stDataFrame"] [class*="header"] {{ text-transform: uppercase; }}
[data-testid="stTable"] {{ width: 100%; }}
[data-testid="stTable"] table {{ border-collapse: collapse; width: 100%; }}
[data-testid="stTable"] th {{
    color: {t["muted"]} !important; font-size: .72rem !important;
    text-transform: uppercase; letter-spacing: .05em;
    border-bottom: 1px solid {t["border"]} !important;
    background-color: #F8FAFC !important;
    padding: 10px 14px !important;
}}
[data-testid="stTable"] td {{
    font-variant-numeric: tabular-nums;
    color: {t["text"]} !important;
    border-bottom: 1px solid {t["border_subtle"]} !important;
    padding: 10px 14px !important;
}}
[data-testid="stTable"] tr:last-child td {{
    border-bottom: none !important;
}}

/* ---------- Expander, bottoni, input ---------- */
[data-testid="stExpander"] {{
    background: {t["surface"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: 12px !important;
    box-shadow: 0 1px 3px rgba(15, 27, 45, 0.04) !important;
}}
[data-testid="stExpander"] details summary p,
[data-testid="stExpander"] details summary span {{
    color: {t["text"]} !important;
    font-weight: 600;
}}
.stButton > button {{
    border-radius: 8px; border: 1px solid {t["border"]};
    background: {t["surface"]}; color: {t["text"]}; font-weight: 600;
    box-shadow: 0 1px 2px rgba(15, 27, 45, 0.04);
    transition: all .15s ease;
}}
.stButton > button:hover {{
    border-color: {t["accent"]}; color: {t["accent"]};
    background: {t["card_hover"]};
}}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {{
    background: {t["accent"]} !important;
    border: 1px solid {t["accent"]} !important;
    color: #FFFFFF !important;
    box-shadow: 0 1px 3px rgba(13, 148, 136, 0.3) !important;
}}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {{
    background: {t["accent_hover"]} !important;
    border-color: {t["accent_hover"]} !important;
    color: #FFFFFF !important;
}}
.stDownloadButton > button {{
    border-radius: 8px; font-weight: 600;
    background: {t["accent"]}; border: 1px solid {t["accent"]}; color: #FFFFFF;
    box-shadow: 0 1px 3px rgba(13, 148, 136, 0.3);
    transition: background .15s ease;
}}
.stDownloadButton > button:hover {{
    background: {t["accent_hover"]}; border-color: {t["accent_hover"]}; color: #FFFFFF;
}}
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label, [data-testid="stWidgetLabel"] span {{
    color: {t["muted"]} !important; font-size: .82rem;
}}
input, textarea, select {{
    color: {t["text"]} !important;
}}
/* ---------- Campi input (text_input, number_input, text_area, date_input, selectbox) ---------- */
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stTextAreaRootElement"],
[data-testid="stDateInputField"],
div[data-baseweb="input"],
div[data-baseweb="base-input"],
div[data-baseweb="select"] > div {{
    border: 1px solid {t["border"]} !important;
    background-color: {t["surface"]} !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(15, 27, 45, 0.04) !important;
    transition: border-color .15s ease, box-shadow .15s ease !important;
}}

[data-testid="stTextInputRootElement"]:hover,
[data-testid="stNumberInputContainer"]:hover,
[data-testid="stTextAreaRootElement"]:hover,
div[data-baseweb="input"]:hover,
div[data-baseweb="select"] > div:hover {{
    border-color: {t["muted"]} !important;
}}

[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
div[data-baseweb="input"]:focus-within,
div[data-baseweb="select"] > div:focus-within {{
    border-color: {t["accent"]} !important;
    box-shadow: 0 0 0 3px {t["accent_soft"]} !important;
}}

input::placeholder, textarea::placeholder {{
    color: #94A3B8 !important;
}}

/* ---------- Tabs ---------- */
button[data-baseweb="tab"] p, button[data-baseweb="tab"] div {{
    color: {t["muted"]};
    font-weight: 500;
}}
button[data-baseweb="tab"][aria-selected="true"] p, button[data-baseweb="tab"][aria-selected="true"] div {{
    color: {t["accent"]} !important;
    font-weight: 700;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    border-bottom-color: {t["accent"]} !important;
}}

/* ---------- Metriche native ---------- */
[data-testid="stMetric"] {{
    background: {t["card"]}; border: 1px solid {t["border"]};
    border-radius: 12px; padding: 12px 14px;
    box-shadow: 0 1px 3px rgba(15, 27, 45, 0.06);
}}
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] span {{
    color: {t["muted"]} !important;
}}
[data-testid="stMetricValue"] {{
    font-variant-numeric: tabular-nums;
    color: {t["text"]} !important;
    white-space: nowrap !important;
}}

/* ---------- Plotly: card attorno al grafico ---------- */
[data-testid="stPlotlyChart"] {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 12px; padding: 8px 10px 4px; margin: 8px 0 10px; overflow: hidden;
    box-shadow: 0 1px 4px rgba(15, 27, 45, 0.06);
}}

/* ---------- Barra periodo (sempre visibile in alto) ---------- */
[data-testid="stLayoutWrapper"]:has(> .st-key-topbar) {{
    position: sticky; top: 3.25rem; z-index: 990;
}}
.st-key-topbar {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 12px; padding: 10px 14px 4px; margin: 0 0 10px;
    box-shadow: 0 2px 8px rgba(15, 27, 45, 0.08);
}}
.st-key-topbar [data-testid="stForm"] {{ border: none; padding: 0; }}
.st-key-topbar button {{ white-space: nowrap; }}
.st-key-topbar [data-testid="stWidgetLabel"] p {{
    font-size: .72rem; text-transform: uppercase;
    letter-spacing: .05em; color: {t["muted"]} !important;
}}
.st-key-topbar [data-testid="stCaptionContainer"] p,
.st-key-topbar .stCaption p {{
    color: {t["muted"]} !important;
}}
.st-key-topbar [data-testid="stCaptionContainer"] strong,
.st-key-topbar .stCaption strong {{
    color: {t["text"]} !important;
}}

/* ---------- Pill / badge ---------- */
.ds-pill {{
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    font-size: .75rem; font-weight: 600; background: {t["accent_soft"]};
    color: {t["accent"]}; border: 1px solid {t["accent"]};
}}
"""


def apply_theme() -> None:
    st.markdown(f"<style>{_css()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# page_setup — da chiamare come PRIMA istruzione di ogni pagina
# ---------------------------------------------------------------------------
def page_setup(page_title: str, icon: str | None = None, subtitle: str | None = None,
               *, layout: str = "wide") -> None:
    st.set_page_config(page_title=page_title, page_icon=icon if icon else None, layout=layout)
    apply_theme()
    sub = f'<p class="ds-sub">{subtitle}</p>' if subtitle else ""
    icon_html = f'<div class="ds-icon">{icon}</div>' if icon else ""
    st.markdown(
        f'<div class="ds-header">{icon_html}'
        f"<div><h1>{page_title}</h1>{sub}</div></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Componenti
# ---------------------------------------------------------------------------
def section(title: str, caption: str | None = None) -> None:
    """Titolo di sezione: barra accent + testo. Sostituisce st.subheader."""
    st.markdown(f'<div class="ds-section"><div class="ds-bar"></div>'
                f"<h2>{title}</h2></div>", unsafe_allow_html=True)
    if caption:
        st.markdown(f'<p class="ds-caption">{caption}</p>', unsafe_allow_html=True)


def metric_cards(cards: list[dict], n_cols: int | None = None) -> None:
    """Griglia di card KPI. Ogni dict: label, value (già formattata),
    delta (opzionale, testo tipo '+12,3%'), delta_good (bool, default True)."""
    t = _t()
    n = n_cols or len(cards)
    html = ['<div class="ds-cards">']
    for c in cards:
        delta = ""
        if c.get("delta") is not None:
            good = c.get("delta_good", True)
            col = t["positive"] if good else t["negative"]
            delta = f'<p class="ds-delta" style="color:{col}">{c["delta"]}</p>'
        html.append(
            f'<div class="ds-card"><p class="ds-label">{c["label"]}</p>'
            f'<p class="ds-value">{c["value"]}</p>{delta}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def data_table(df, col_config: dict | None = None, *, key: str | None = None) -> None:
    """Tabella dati standard dell'app (st.dataframe già stilizzato dal CSS)."""
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config=col_config or {}, key=key)


def empty_state(message: str, icon: str = "") -> None:
    icon_str = f"{icon}&nbsp;&nbsp;" if icon else ""
    st.markdown(
        f'<div style="text-align:center;padding:28px;color:{_t()["muted"]};'
        f'border:1px dashed {_t()["border"]};border-radius:12px;margin:8px 0;">'
        f'{icon_str}{message}</div>', unsafe_allow_html=True)


def style_fig(fig, y_title: str | None = None):
    """Applica il tema enterprise light ai grafici Plotly (font, griglia, sfondo trasparente,
    palette serie coerente). Ritorna il fig per chaining."""
    t = _t()
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif",
                  color=t["text"], size=13),
        title_text="",                            # il titolo è nella section() della pagina
        margin=dict(l=10, r=40, t=46, b=10),
        # legenda in alto, in uno spazio riservato (senza titolo del grafico): in basso finiva
        # sopra il titolo dell'asse X e le etichette ruotate
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text="",
                    font=dict(color=t["text"], size=12)),
        colorway=SERIES,
    )
    fig.update_xaxes(
        gridcolor=t["grid"],
        zerolinecolor=t["grid"],
        tickfont=dict(color=t["text"]),
        title_font=dict(color=t["text"]),
        automargin=True,
        title_standoff=12
    )
    fig.update_yaxes(
        gridcolor=t["grid"],
        zerolinecolor=t["grid"],
        tickfont=dict(color=t["text"]),
        title_font=dict(color=t["text"]),
        automargin=True,
        title_standoff=12
    )
    if y_title:
        fig.update_yaxes(title_text=y_title, title_font=dict(color=t["text"]))
    return fig


def chart(fig, *, y_title: str | None = None) -> None:
    """Plotly chart con card attorno: ds.style_fig + container + st.plotly_chart."""
    style_fig(fig, y_title)
    st.plotly_chart(fig, width="stretch")


def pill(text: str) -> None:
    st.markdown(f'<span class="ds-pill">{text}</span>', unsafe_allow_html=True)


def it_num(x: float, decimali: int = 0) -> str:
    """Numero in stile italiano: 1.234.567,8 (per metric_cards)."""
    x = 0.0 if round(x, decimali) == 0 else x          # niente "-0,00"
    s = f"{x:,.{decimali}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
