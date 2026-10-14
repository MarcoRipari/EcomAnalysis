from datetime import date, datetime
import streamlit as st

from core import db, ferie, roles
from core.design_system import page_setup

page_setup("Calendario", None)

conn = db.connect()
ferie.init_ferie_tables(conn)

df_storico = ferie.get_ferie_storico(conn)

oggi = datetime.now().date()
if "cal_anno" not in st.session_state:
    st.session_state.cal_anno = oggi.year
    st.session_state.cal_mese = oggi.month

c_prev, c_titolo, c_oggi, c_next = st.columns([1, 4, 1, 1])
with c_prev:
    if st.button("Mese precedente", use_container_width=True, key="cal_btn_prev"):
        m = st.session_state.cal_mese - 1
        a = st.session_state.cal_anno
        if m < 1:
            m = 12
            a -= 1
        st.session_state.cal_mese = m
        st.session_state.cal_anno = a
        st.rerun()

with c_titolo:
    nome_mese = ferie.MESI_IT_LUNGO[st.session_state.cal_mese - 1]
    st.markdown(
        f"<h3 style='text-align:center; margin:4px 0; color:#0F172A;'>"
        f"{nome_mese} {st.session_state.cal_anno}</h3>",
        unsafe_allow_html=True,
    )

with c_oggi:
    if st.button("Oggi", use_container_width=True, key="cal_btn_oggi"):
        st.session_state.cal_anno = oggi.year
        st.session_state.cal_mese = oggi.month
        st.rerun()

with c_next:
    if st.button("Mese successivo", use_container_width=True, key="cal_btn_next"):
        m = st.session_state.cal_mese + 1
        a = st.session_state.cal_anno
        if m > 12:
            m = 1
            a += 1
        st.session_state.cal_mese = m
        st.session_state.cal_anno = a
        st.rerun()

html_mensile = ferie.build_calendario_mensile_html(
    df_storico, st.session_state.cal_anno, st.session_state.cal_mese
)
st.html(html_mensile)

st.markdown(
    "<div style='display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:#64748B; margin-top:14px;'>"
    "<span><b style='color:#0D9488;'>Bordo Teal:</b> Giorno odierno</span>"
    "<span><b style='color:#B45309;'>Giallo chiaro:</b> Festività italiana</span>"
    "<span><b style='color:#64748B;'>Grigio chiaro:</b> Weekend</span>"
    "<span><b style='color:#0F172A;'>🕐 Nome:</b> Permesso orario (entrata posticipata / uscita anticipata)</span>"
    "</div>",
    unsafe_allow_html=True,
)
