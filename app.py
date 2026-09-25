import datetime as dt

import streamlit as st

from core import db, pipeline as pl
from core.ui_helpers import shift_year

st.set_page_config(page_title="Pannello Report E-commerce", page_icon="🚀", layout="wide")

st.title("🚀 Pannello Report — E-commerce BI")
st.caption(
    "I dati vivono nel DB (pagina **⬆️ Carica Dati**): qui scegli solo il periodo da "
    "analizzare — nessun file da ricaricare ad ogni report."
)

conn = db.connect()
stats = db.get_stats(conn)

if stats["righe_totali"] == 0:
    st.info("⬅️ Il DB è vuoto. Vai alla pagina **⬆️ Carica Dati** e carica almeno un DATASET.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Righe nel DB", f"{stats['righe_totali']:,}".replace(",", "."))
c2.metric("Spedite", f"{stats['spediti']:,}".replace(",", "."))
c3.metric("Rese", f"{stats['resi']:,}".replace(",", "."))
c4.metric("Rimborsi extra", f"{stats['standalone']:,}".replace(",", "."))
st.caption(f"Copertura dati (Data Pagamento): dal **{stats['data_min']}** al **{stats['data_max']}**.")

data_min = dt.date.fromisoformat(stats["data_min"])
data_max = dt.date.fromisoformat(stats["data_max"])


def _shift_year(d: dt.date, years: int) -> dt.date:
    return shift_year(d, years)


with st.sidebar:
    st.session_state["periodo_a"]
    st.header("1️⃣ Periodo di analisi")
    periodo_a = st.date_input(
        "Periodo corrente", value=(max(data_min, _shift_year(data_max, -1)), data_max),
        min_value=data_min, max_value=data_max, key="periodo_a",
    )

    confronta = st.checkbox("Confronta con un altro periodo (Y2Y)", value=True)
    periodo_b = None
    if confronta and isinstance(periodo_a, tuple) and len(periodo_a) == 2:
        default_b = (max(data_min, _shift_year(periodo_a[0], -1)), min(data_max, _shift_year(periodo_a[1], -1)))
        periodo_b = st.date_input("Periodo di confronto", value=default_b,
                                   min_value=data_min, max_value=data_max, key="periodo_b")

    st.header("2️⃣ Perimetro logistico")
    perimetro_label = st.radio(
        "Su quale perimetro calcolare i report?",
        ["TOTALE (Diretti + Logistica Esterna)", "SOLO DIRETTI", "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)"],
        index=0,
    )
    perimetro = {"TOTALE (Diretti + Logistica Esterna)": "1", "SOLO DIRETTI": "2",
                 "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)": "3"}[perimetro_label]

    with st.expander("Anagrafica articoli (facoltativa)"):
        st.caption("Serve per descrizioni, serie, classificazione per genere (Taglie) e foto.")
        anagrafica_file = st.file_uploader("ANAGRAFICA", type=["csv", "txt"], key="anag_home")
        if anagrafica_file is not None:
            st.session_state["anagrafica_file"] = anagrafica_file

    periodo_a_ok = isinstance(periodo_a, tuple) and len(periodo_a) == 2
    periodo_b_ok = (not confronta) or (isinstance(periodo_b, tuple) and len(periodo_b) == 2)
    genera = st.button("▶️ Genera dati report", type="primary", use_container_width=True,
                        disabled=not (periodo_a_ok and periodo_b_ok))

if genera:
    from core import engine
    anagrafica = (engine.load_anagrafica(st.session_state["anagrafica_file"])
                  if st.session_state.get("anagrafica_file") else {})
    with st.spinner("Interrogazione DB…"):
        try:
            result = pl.build_pipeline_from_db(
                conn,
                periodo_current=periodo_a,
                periodo_old=periodo_b if (confronta and periodo_b_ok) else None,
                perimetro=perimetro,
                anagrafica=anagrafica,
            )
            st.session_state["pipeline"] = result
            st.session_state["perimetro_label"] = perimetro_label
            st.session_state["periodo_a"] = periodo_a
            st.session_state["periodo_b"] = periodo_b if (confronta and periodo_b_ok) else None
            st.session_state["periodo_a_label"] = f"{periodo_a[0]} → {periodo_a[1]}"
            st.session_state["periodo_b_label"] = f"{periodo_b[0]} → {periodo_b[1]}" if (confronta and periodo_b_ok) else None
        except Exception as e:
            st.exception(e)
            st.stop()

pipe = st.session_state.get("pipeline")

if pipe is None:
    st.info("⬅️ Scegli il periodo (ed eventualmente quello di confronto) e premi **Genera dati report**.")
else:
    st.success(
        f"✅ Dati pronti — periodo corrente **{st.session_state['periodo_a_label']}**"
        + (f", confronto **{st.session_state['periodo_b_label']}**" if st.session_state.get("periodo_b_label") else "")
        + ". Naviga tra i report dal menu a sinistra."
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("Righe periodo corrente", f"{len(pipe.current_data):,}".replace(",", "."))
    m2.metric("Righe periodo confronto", f"{len(pipe.old_data):,}".replace(",", "."))
    m3.metric("Rimborsi extra nel periodo", f"{len(pipe.esito_resi_current['standalone']):,}".replace(",", "."))
    st.caption(
        "\"Rimborsi extra\" = ordini rimborsati nel periodo corrente ma spediti prima (o senza "
        "spedito noto): riducono il fatturato netto reale del periodo pur non essendo conteggiati "
        "come vendita del periodo stesso."
    )
