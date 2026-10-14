"""
Barra periodo — sempre visibile in alto, su ogni pagina.

Viene disegnata da app.py PRIMA di pg.run(), quindi è presente indipendentemente dalla pagina
aperta. Scelta di perimetro, periodo e confronto + "Applica": costruisce la Pipeline dal DB e
la mette in st.session_state (le stesse chiavi che le pagine leggono).
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from . import config as CFG
from . import db, pipeline
from .ui_helpers import shift_year

PERIMETRI_BASE = {
    "Totale": "1",
    "Canali Diretti": "2",
}
PERIMETRI = PERIMETRI_BASE


def get_perimetri(conn, start, end) -> dict[str, str]:
    """Costruisce le opzioni di perimetro per il periodo dato:
    Totale, Canali Diretti e i singoli canali esterni presenti nel periodo (es. Zalando ZFS, Amazon FBA)."""
    p = dict(PERIMETRI_BASE)
    esterni = db.canali_esterni_attivi(conn, start, end)
    for label, code in esterni:
        p[label] = code
    return p


def anno_fiscale(oggi: dt.date, indietro: int = 0) -> tuple[dt.date, dt.date]:
    """Anno fiscale aziendale (1° novembre → 31 ottobre) che contiene `oggi`, spostato di `indietro` anni.
    Es. oggi = 11/10/2026 ⇒ 01/11/2025 → 31/10/2026."""
    m = CFG.MESE_INIZIO_ANNO_FISCALE
    inizio_anno = oggi.year if oggi.month >= m else oggi.year - 1
    inizio = dt.date(inizio_anno - indietro, m, 1)
    fine = dt.date(inizio.year + 1, m, 1) - dt.timedelta(days=1)
    return inizio, fine


def periodo_predefinito(oggi: dt.date, data_min: dt.date, data_max: dt.date) -> tuple[dt.date, dt.date]:
    """Periodo caricato all'avvio: l'anno fiscale corrente, limitato ai dati disponibili (fino all'ultima
    data presente). Se l'anno fiscale corrente non ha ancora dati (es. appena iniziato) si usa il precedente;
    se il DB non copre nessun anno fiscale recente, gli ultimi 12 mesi di dati."""
    for indietro in range(4):
        inizio, fine = anno_fiscale(oggi, indietro)
        inizio, fine = max(inizio, data_min), min(fine, data_max)
        if inizio <= fine:
            return inizio, fine
    return max(data_min, shift_year(data_max, -1)), data_max


def _coperti(periodo: tuple, data_min: dt.date, data_max: dt.date) -> tuple | None:
    """Periodo spostato di un anno indietro, ristretto alla copertura del DB (None se non coperto)."""
    a0 = max(data_min, shift_year(periodo[0], -1))
    a1 = min(data_max, shift_year(periodo[1], -1))
    return (a0, a1) if a0 <= a1 else None


def genera(conn, periodo_a: tuple, perimetro_label: str, confronta_2anni: bool,
           data_min: dt.date, data_max: dt.date, perimetro_code: str | None = None) -> None:
    """Interroga il DB e aggiorna session_state (pipeline + selezioni usate dalle pagine)."""
    periodo_b = _coperti(periodo_a, data_min, data_max)
    ss = st.session_state
    anag = ss.get("anagrafica") or db.get_anagrafica_dict(conn)
    ss["anagrafica"] = anag

    if perimetro_code is None:
        perimetri = get_perimetri(conn, periodo_a[0], periodo_a[1])
        perimetro_code = perimetri.get(perimetro_label, "1")

    result = pipeline.build_pipeline_from_db(
        conn, periodo_current=periodo_a, periodo_old=periodo_b,
        perimetro=perimetro_code, anagrafica=anag)
    ss["pipeline"] = result
    ss["perimetro_label"] = perimetro_label
    ss["perimetro_code"] = perimetro_code
    ss["sel_periodo_a"] = periodo_a
    ss["sel_periodo_b"] = periodo_b
    ss["periodo_a_label"] = f"{periodo_a[0]} → {periodo_a[1]}"
    ss["periodo_b_label"] = f"{periodo_b[0]} → {periodo_b[1]}" if periodo_b else None
    ss["sel_confronta_2anni"] = confronta_2anni
    ss.pop("export_df", None)          # l'export precedente non vale più


def render() -> None:
    conn = db.connect()
    d0, d1 = db.get_data_bounds(conn)
    ss = st.session_state

    with st.container(key="topbar"):
        if d0 is None:
            st.info("Il DB è vuoto: carica i file DATASET e RESI da **Export & Sistema → Carica Dati**.")
            return
        data_min, data_max = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)

        # un nuovo file ANAGRAFICA (caricato in Carica Dati) richiede di rigenerare con la stessa selezione
        rigenera = ss.pop("rigenera_pipeline", False) and "sel_periodo_a" in ss
        default = ss.get("sel_periodo_a") or periodo_predefinito(dt.date.today(), data_min, data_max)
        periodo_rif = ss.get("sel_periodo_a") or default
        perimetri = get_perimetri(conn, periodo_rif[0], periodo_rif[1])

        curr_label = ss.get("perimetro_label")
        if curr_label not in perimetri:
            if curr_label in ("Solo Diretti", "2"):
                curr_label = "Canali Diretti"
            elif curr_label in ("Solo Esterni (ZFS/FBA/AMZ)", "3"):
                curr_label = next((k for k in perimetri if k not in PERIMETRI_BASE), "Totale")
            else:
                curr_label = "Totale"

        perimetro_idx = list(perimetri).index(curr_label) if curr_label in perimetri else 0

        with st.form("topbar_form", border=False):
            c_per, c_date, c_conf, c_btn = st.columns([2.2, 3, 2.6, 1.5], vertical_alignment="bottom")
            perimetro_label = c_per.selectbox(
                "Perimetro", list(perimetri),
                index=perimetro_idx)
            periodo_a = c_date.date_input(
                "Periodo di Analisi", value=default, min_value=data_min, max_value=data_max, format="DD/MM/YYYY",
                help=f"Dati disponibili dal {data_min:%d/%m/%Y} al {data_max:%d/%m/%Y}. "
                     "Il confronto con l'anno precedente è automatico.")
            confronta_2anni = c_conf.checkbox("Includi Confronto Triennale (Y-2)",
                                              value=ss.get("sel_confronta_2anni", False))
            applica = c_btn.form_submit_button("Applica", type="primary", width="stretch")

        periodo_ok = isinstance(periodo_a, (tuple, list)) and len(periodo_a) == 2
        if applica and not periodo_ok:
            st.warning("Seleziona sia la data iniziale sia quella finale del periodo.")

        da_generare = (applica and periodo_ok) or rigenera or "pipeline" not in ss
        if da_generare:
            periodo = tuple(periodo_a) if periodo_ok else tuple(default)
            perim_map = get_perimetri(conn, periodo[0], periodo[1])
            code = perim_map.get(perimetro_label, "1")
            with st.spinner("Calcolo dei dati…"):
                genera(conn, periodo, perimetro_label, confronta_2anni, data_min, data_max, perimetro_code=code)

        if "pipeline" in ss:
            conf = f" · confronto **{ss['periodo_b_label']}**" if ss.get("periodo_b_label") else \
                " · confronto anno precedente **non coperto dal DB**"
            st.caption(f"Periodo applicato: **{ss['periodo_a_label']}**{conf} · {ss['perimetro_label']}")
