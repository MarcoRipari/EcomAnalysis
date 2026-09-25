import streamlit as st

from core import db

st.set_page_config(page_title="Log Riconciliazione", page_icon="🔍", layout="wide")
st.title("🔍 Log Riconciliazione")
st.caption(
    "Storico permanente di tutti i caricamenti RESI: ogni riga viene loggata al momento "
    "dell'upload (convertita, duplicata o rimborso extra), indipendentemente dal periodo poi "
    "scelto in home per i report."
)

conn = db.connect()

log_upload = db.get_upload_log(conn)
files_resi = sorted(log_upload.loc[log_upload["tipo"] == "RESI", "fonte_file"].unique().tolist()) \
    if not log_upload.empty else []

col1, col2 = st.columns(2)
with col1:
    filtro_file = st.selectbox("Filtra per file RESI", ["(tutti)"] + files_resi)
with col2:
    filtro_esito = st.selectbox("Filtra per esito", ["(tutti)", "convertito", "duplicato", "standalone"])

df = db.get_match_log(
    conn,
    fonte_file=None if filtro_file == "(tutti)" else filtro_file,
    esito=None if filtro_esito == "(tutti)" else filtro_esito,
)

if df.empty:
    st.caption("Nessuna riga di log (carica un file RESI dalla pagina ⬆️ Carica Dati).")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Convertiti", int((df["esito"] == "convertito").sum()))
    c2.metric("Duplicati", int((df["esito"] == "duplicato").sum()))
    c3.metric("Standalone (rimborsi extra)", int((df["esito"] == "standalone").sum()))
    st.dataframe(df, hide_index=True, use_container_width=True, height=600)

st.divider()
st.subheader("🕒 Storico caricamenti (DATASET + RESI)")
st.dataframe(log_upload, hide_index=True, use_container_width=True)
