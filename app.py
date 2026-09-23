import streamlit as st

from core import pipeline as pl

st.set_page_config(page_title="Pannello Report E-commerce", page_icon="🚀", layout="wide")

st.title("🚀 Pannello Report — E-commerce BI")
st.caption(
    "Porting Python/Streamlit del sistema Google Apps Script di reportistica sell-out. "
    "Carica i file, genera i dati una volta sola, poi naviga tra i report nel menu a sinistra."
)

with st.sidebar:
    st.header("1️⃣ Dati sorgente")
    dataset_current_file = st.file_uploader("DATASET (anno corrente) *", type=["csv"])
    resi_current_file = st.file_uploader("RESI (anno corrente) *", type=["csv"])

    with st.expander("Anno precedente (per i report Y2Y / Carryover)"):
        dataset_old_file = st.file_uploader("DATASET OLD", type=["csv"], key="ds_old")
        resi_old_file = st.file_uploader("RESI OLD", type=["csv"], key="resi_old")

    with st.expander("Anagrafica articoli (facoltativa)"):
        st.caption("Serve per descrizioni, serie, classificazione per genere (Taglie) e foto. "
                    "Layout posizionale: colonna A=SKU, E=Collezione, F=Serie, G=Codice, "
                    "J=Descrizione, N=Genere.")
        anagrafica_file = st.file_uploader("ANAGRAFICA", type=["csv"], key="anag")

    st.header("2️⃣ Perimetro logistico")
    perimetro_label = st.radio(
        "Su quale perimetro calcolare i report?",
        ["TOTALE (Diretti + Logistica Esterna)", "SOLO DIRETTI", "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)"],
        index=0,
    )
    perimetro = {"TOTALE (Diretti + Logistica Esterna)": "1", "SOLO DIRETTI": "2",
                 "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)": "3"}[perimetro_label]

    genera = st.button("▶️ Genera dati report", type="primary", use_container_width=True,
                        disabled=not (dataset_current_file and resi_current_file))

if genera:
    with st.spinner("Elaborazione dataset in corso…"):
        try:
            result = pl.run_pipeline(
                dataset_current_file=dataset_current_file,
                resi_current_file=resi_current_file,
                dataset_old_file=dataset_old_file,
                resi_old_file=resi_old_file,
                anagrafica_file=anagrafica_file,
                perimetro=perimetro,
            )
            st.session_state["pipeline"] = result
            st.session_state["perimetro_label"] = perimetro_label
        except Exception as e:
            st.exception(e)
            st.stop()

pipe = st.session_state.get("pipeline")

if pipe is None:
    st.info(
        "⬅️ Carica almeno **DATASET** e **RESI** dell'anno corrente nella barra laterale, "
        "scegli il perimetro logistico e premi **Genera dati report**.\n\n"
        "I report Y2Y, Collezioni, Codici, Carryover e Sell-Through richiedono anche i file "
        "dell'anno precedente / BUYING (caricabili nella pagina Sell-Through)."
    )
else:
    diag_pre = pipe.diag_pre_filtro
    diag_post = pipe.diag_post_filtro
    st.success("✅ Dati elaborati con successo. Naviga tra i report dal menu a sinistra.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Perimetro selezionato", st.session_state.get("perimetro_label", ""))
    c2.metric("Righe DATASET post-filtro", f"{len(pipe.current_data):,}".replace(",", "."))
    c3.metric("Righe DATASET OLD post-filtro", f"{len(pipe.old_data):,}".replace(",", "."))

    with st.expander("📊 Diagnostica canali logistici (DIRETTO vs ESTERNA)"):
        st.write(
            f"**Pre-filtro** → DIRETTO: {diag_pre['righeDiretti']} righe / {diag_pre['ordiniDiretti']} ordini "
            f"— ESTERNA: {diag_pre['righeEsterni']} righe / {diag_pre['ordiniEsterni']} ordini"
        )
        st.write(
            f"**Post-filtro** → DIRETTO: {diag_post['righeDiretti']} righe / {diag_post['ordiniDiretti']} ordini "
            f"— ESTERNA: {diag_post['righeEsterni']} righe / {diag_post['ordiniEsterni']} ordini"
        )
        st.caption(
            "Se ESTERNA risulta 0 anche quando sai che esistono ordini ZFS/FBA/AMZ, il problema "
            "è nel formato/colonna di ORDINE_ID (colonna I del CSV), non nel filtro perimetro."
        )

    esito = pipe.esito_resi_current
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Resi riconciliati (convertiti)", len(esito["convertiti"]))
    r2.metric("Resi duplicati scartati", len(esito["duplicati"]))
    r3.metric("Rimborsi extra (standalone)", len(esito["standalone"]))
    r4.metric("Resi fuori periodo", len(esito["fuoriPeriodo"]))
