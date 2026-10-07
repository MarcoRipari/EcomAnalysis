"""EcomAnalysis Design System — tema enterprise dark/light + componenti UI.

Unico punto di verità per l'aspetto dell'app. Ogni pagina Streamlit chiama
`page_setup()` come PRIMA cosa (sostituisce st.set_page_config + st.title) e
usa i componenti qui sotto (metric_cards, section, data_table, style_fig).

Token e regole sono documentati nel design system (canvas "EcomAnalysis Design
System"); i colori sono anche il_contratto per un'eventuale migrazione React.
"""
from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Token — palette ufficiale
# ---------------------------------------------------------------------------
DARK = {
    "bg": "#0B1220",            # fondo app
    "surface": "#111A2C",       # pannelli / sidebar
    "card": "#16233A",          # card KPI
    "card_hover": "#1B2B45",
    "border": "#22304A",
    "text": "#E7EEF8",
    "muted": "#93A1B8",
    "accent": "#14B8A6",        # teal (più vivido su fondo scuro)
    "accent_soft": "rgba(20, 184, 166, 0.14)",
    "positive": "#34D399",
    "negative": "#F87171",
    "warning": "#FBBF24",
    "grid": "rgba(147, 161, 184, 0.15)",
    "font": "'Inter', 'Segoe UI', system-ui, sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, monospace",
}

LIGHT = {
    "bg": "#F5F7FA",
    "surface": "#FFFFFF",
    "card": "#FFFFFF",
    "card_hover": "#F0FDF9",
    "border": "#E2E8F0",
    "text": "#0F1B2D",
    "muted": "#5B6B82",
    "accent": "#0D9488",        # teal brand
    "accent_soft": "rgba(13, 148, 136, 0.10)",
    "positive": "#059669",
    "negative": "#DC2626",
    "warning": "#D97706",
    "grid": "rgba(15, 27, 45, 0.08)",
    "font": "'Inter', 'Segoe UI', system-ui, sans-serif",
    "mono": "'JetBrains Mono', ui-monospace, monospace",
}

# Palette serie (grafici): accent sempre primo, poi neutri/blu coerenti.
SERIES = ["#14B8A6", "#3B82F6", "#F59E0B", "#8B5CF6", "#64748B", "#EC4899"]


def _t() -> dict:
    return DARK if theme_mode() == "dark" else LIGHT


# ---------------------------------------------------------------------------
# Tema — modalità corrente, persistenza, CSS
# ---------------------------------------------------------------------------
def theme_mode() -> str:
    """'dark' (default) oppure 'light'. Persiste in session_state e query param."""
    mode = st.session_state.get("ds_theme")
    if mode not in ("dark", "light"):
        mode = st.query_params.get("theme", "dark")
        if mode not in ("dark", "light"):
            mode = "dark"
        st.session_state["ds_theme"] = mode
    return mode


def set_theme(mode: str) -> None:
    mode = "dark" if mode == "dark" else "light"
    st.session_state["ds_theme"] = mode
    st.query_params["theme"] = mode


def _css() -> str:
    t = _t()
    sel = "html[data-theme='light']" if theme_mode() == "light" else "html"
    # NB: le variabili di Streamlit (--background, --secondary-background-color,
    # --text-color, …) vengono sovrascritte così che anche dataframe, bottoni e
    # input cambino aspetto senza reload del tema statico in config.toml.
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

{sel}, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
    --background: {t["bg"]};
    --secondary-background-color: {t["surface"]};
    --background-color: {t["bg"]};
    --text-color: {t["text"]};
    --secondary-text-color: {t["muted"]};
    --primary-color: {t["accent"]};
    --font: {t["font"]};
    background: {t["bg"]};
    color: {t["text"]};
    font-family: {t["font"]};
}}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background: {t["surface"]};
    border-right: 1px solid {t["border"]};
}}
[data-testid="stSidebar"] * {{ font-family: {t["font"]}; }}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {{
    font-size: .95rem; font-weight: 700; letter-spacing: .02em; color: {t["text"]};
}}

/* ---------- Header pagina ---------- */
.ds-header {{
    display: flex; align-items: center; gap: 14px;
    padding: 10px 4px 2px 0; margin-bottom: 4px;
    border-bottom: 1px solid {t["border"]};
}}
.ds-header .ds-icon {{
    width: 46px; height: 46px; border-radius: 12px; flex: 0 0 auto;
    background: {t["accent_soft"]};
    display: flex; align-items: center; justify-content: center; font-size: 24px;
}}
.ds-header h1 {{
    font-size: 1.55rem; font-weight: 800; letter-spacing: -0.01em;
    margin: 0; color: {t["text"]}; line-height: 1.2;
}}
.ds-header .ds-sub {{ font-size: .85rem; color: {t["muted"]}; margin: 2px 0 0; }}
.ds-header .ds-toggle {{ margin-left: auto; }}

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
.ds-cards {{ display: flex; gap: 14px; margin: 10px 0 6px; }}
.ds-card {{
    flex: 1 1 0; min-width: 0; background: {t["card"]};
    border: 1px solid {t["border"]}; border-radius: 12px;
    padding: 14px 16px 12px;
    transition: background .15s ease, border-color .15s ease;
}}
.ds-card:hover {{ background: {t["card_hover"]}; border-color: {t["accent"]}; }}
.ds-card .ds-label {{
    font-size: .72rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: .06em; color: {t["muted"]}; margin: 0 0 6px; white-space: nowrap;
}}
.ds-card .ds-value {{
    font-size: 1.45rem; font-weight: 800; color: {t["text"]};
    font-variant-numeric: tabular-nums; margin: 0;
}}
.ds-card .ds-delta {{ font-size: .8rem; font-weight: 600; margin: 4px 0 0; }}

/* ---------- Tabelle ---------- */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    border: 1px solid {t["border"]} !important;
    border-radius: 12px !important;
    overflow: hidden;
    background: {t["surface"]};
}}
[data-testid="stDataFrame"] [class*="header"] {{ text-transform: uppercase; }}
[data-testid="stTable"] {{ width: 100%; }}
[data-testid="stTable"] table {{ border-collapse: collapse; }}
[data-testid="stTable"] th {{
    color: {t["muted"]} !important; font-size: .72rem !important;
    text-transform: uppercase; letter-spacing: .05em;
    border-bottom: 1px solid {t["border"]};
}}
[data-testid="stTable"] td {{ font-variant-numeric: tabular-nums; }}

/* ---------- Expander, bottoni, input ---------- */
[data-testid="stExpander"] {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 12px;
}}
.stButton > button {{
    border-radius: 8px; border: 1px solid {t["border"]};
    background: {t["surface"]}; color: {t["text"]}; font-weight: 600;
}}
.stButton > button:hover {{ border-color: {t["accent"]}; color: {t["accent"]}; }}
.stDownloadButton > button {{
    border-radius: 8px; font-weight: 600;
    background: {t["accent"]}; border: none; color: #FFFFFF;
}}
[data-testid="stWidgetLabel"] p {{ color: {t["muted"]}; font-size: .82rem; }}

/* ---------- Metriche native (pagine non ancora migrate) ---------- */
[data-testid="stMetric"] {{
    background: {t["card"]}; border: 1px solid {t["border"]};
    border-radius: 12px; padding: 12px 14px;
}}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}

/* ---------- Plotly: card attorno al grafico ---------- */
.ds-chart {{
    background: {t["surface"]}; border: 1px solid {t["border"]};
    border-radius: 12px; padding: 6px 10px 2px; margin: 8px 0 10px;
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
def page_setup(page_title: str, icon: str, subtitle: str | None = None,
               *, layout: str = "wide") -> None:
    st.set_page_config(page_title=page_title, page_icon=icon, layout=layout)
    apply_theme()
    with st.sidebar:
        _mode = st.radio("Tema", ["dark", "light"],
                         index=0 if theme_mode() == "dark" else 1,
                         label_visibility="collapsed",
                         format_func=lambda m: "🌙 Dark" if m == "dark" else "☀️ Light",
                         key="ds_theme_radio")
        if _mode != st.session_state.get("ds_theme"):
            set_theme(_mode)
            st.rerun()
    sub = f'<p class="ds-sub">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f'<div class="ds-header"><div class="ds-icon">{icon}</div>'
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
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config=col_config or {}, key=key)


def empty_state(message: str, icon: str = "🗂️") -> None:
    st.markdown(
        f'<div style="text-align:center;padding:28px;color:{_t()["muted"]};'
        f'border:1px dashed {_t()["border"]};border-radius:12px;margin:8px 0;">'
        f'{icon}&nbsp;&nbsp;{message}</div>', unsafe_allow_html=True)


def style_fig(fig, y_title: str | None = None):
    """Applica il tema ai grafici Plotly (font, griglia, sfondo trasparente,
    palette serie coerente). Ritorna il fig per chaining."""
    t = _t()
    fig.update_layout(
        template="plotly_white" if theme_mode() == "light" else "plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif",
                  color=t["text"], size=13),
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        colorway=SERIES,
    )
    fig.update_xaxes(gridcolor=t["grid"], zerolinecolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"], zerolinecolor=t["grid"])
    if y_title:
        fig.update_yaxes(title_text=y_title)
    return fig


def chart(fig, *, y_title: str | None = None) -> None:
    """Plotly chart con card attorno: ds.style_fig + container + st.plotly_chart."""
    style_fig(fig, y_title)
    st.markdown('<div class="ds-chart">', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def pill(text: str) -> None:
    st.markdown(f'<span class="ds-pill">{text}</span>', unsafe_allow_html=True)


def it_num(x: float, decimali: int = 0) -> str:
    """Numero in stile italiano: 1.234.567,8 (per metric_cards)."""
    s = f"{x:,.{decimali}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
