import streamlit as st

from core import db, engine, pipeline as pl

st.set_page_config(page_title="Carica Dati", page_icon="⬆️", layout="wide")
st.title("⬆️ Carica Dati — aggiornamento incrementale del DB")

st.caption(
    "Carica qui i file DATASET e RESI (CSV o TXT) man mano che li ricevi. Ogni file viene "
    "elaborato una volta e le sue righe finiscono nel DB: ricaricare lo stesso file non crea "
    "duplicati. I RESI aggiornano lo stato delle righe DATASET già presenti (Spedito→Reso) "
    "senza toccare il loro numero ordine. Per generare i report vai alla home e scegli un "
    "range di date — non serve più ricaricare nulla."
)

conn = db.connect()

with st.expander("⚙️ Correzione Nazione per TXT grezzi (facoltativa)"):
    attiva_correzione_naz = st.checkbox("Attiva correzione Nazione", value=False, key="corr_naz_upload")
    col_sito_nazione = None
    if attiva_correzione_naz:
        col_sito_nazione = st.number_input(
            "Indice colonna 'Sito esteso' (0-based, la tua colonna Q)", min_value=0, value=16, step=1,
            key="col_sito_upload",
        )

anagrafica_file = st.session_state.get("anagrafica_file")


def _process_and_show(files, tipo: str):
    if not files:
        return
    anagrafica = engine.load_anagrafica(anagrafica_file) if anagrafica_file else {}
    for f in files:
        status_box = st.status(f"Elaborazione **{f.name}**…", expanded=True)
        try:
            status_box.write("Lettura file…")
            raw = engine.read_raw_csv(f)
            if col_sito_nazione is not None:
                status_box.write("Correzione Nazione…")
                engine.apply_nazione_correction_inplace(raw, col_sito_nazione)
            status_box.write(f"Normalizzazione righe ({len(raw):,} righe)…".replace(",", "."))
            processed = engine.process_dataset(raw, anagrafica)
            del raw

            progress_bar = status_box.progress(0.0)

            def on_progress(done, total, fase="scrittura DB"):
                progress_bar.progress(min(done / total, 1.0) if total else 1.0, text=f"{fase}: {done:,}/{total:,}".replace(",", "."))

            if tipo == "DATASET":
                status_box.write("Scrittura nel DB…")
                stats = db.upsert_dataset(conn, processed, f.name, progress=on_progress)
                status_box.update(label=f"✅ {f.name}", state="complete")
                st.success(
                    f"**{f.name}** — {stats['righe_nel_file']:,} righe nel file, "
                    f"{stats['righe_nuove']:,} nuove, {stats['righe_gia_presenti']:,} già presenti "
                    "(ignorate)."
                    .replace(",", ".")
                )
            else:
                status_box.write("Ricerca corrispondenze e scrittura nel DB…")
                stats = db.upsert_resi(conn, processed, f.name, progress=on_progress)
                status_box.update(label=f"✅ {f.name}", state="complete")
                st.success(
                    f"**{f.name}** — {len(processed):,} righe nel file: "
                    f"{stats['convertiti']:,} convertite Spedito→Reso, "
                    f"{stats['duplicati']:,} già riconciliate (scartate), "
                    f"{stats['standalone']:,} rimborsi extra senza spedito noto."
                    .replace(",", ".")
                )
        except MemoryError:
            status_box.update(label=f"❌ {f.name} — memoria esaurita", state="error")
            st.error(
                f"**{f.name}**: memoria esaurita durante l'elaborazione. Su file da centinaia di "
                "migliaia di righe, prova a: (1) caricare un file alla volta invece che in blocco, "
                "(2) se possibile dividere il file in parti più piccole prima di caricarlo, oppure "
                "(3) valutare un piano Streamlit Cloud con più RAM del tier gratuito."
            )
        except Exception as e:
            status_box.update(label=f"❌ {f.name} — errore", state="error")
            st.error(f"**{f.name}**: caricamento fallito, nessuna riga di questo file è stata salvata.")
            st.exception(e)


col1, col2 = st.columns(2)
with col1:
    st.subheader("📦 File DATASET")
    dataset_files = st.file_uploader("Uno o più file DATASET", type=["csv", "txt"],
                                      accept_multiple_files=True, key="up_dataset")
    if st.button("Carica DATASET nel DB", disabled=not dataset_files, use_container_width=True):
        _process_and_show(dataset_files, "DATASET")

with col2:
    st.subheader("↩️ File RESI")
    resi_files = st.file_uploader("Uno o più file RESI", type=["csv", "txt"],
                                   accept_multiple_files=True, key="up_resi")
    if st.button("Carica RESI nel DB", disabled=not resi_files, use_container_width=True):
        _process_and_show(resi_files, "RESI")

st.divider()
st.subheader("📊 Stato del DB")
stats = db.get_stats(conn)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Righe totali", f"{stats['righe_totali']:,}".replace(",", "."))
c2.metric("Spedite", f"{stats['spediti']:,}".replace(",", "."))
c3.metric("Rese", f"{stats['resi']:,}".replace(",", "."))
c4.metric("Rimborsi extra", f"{stats['standalone']:,}".replace(",", "."))
if stats["data_min"]:
    st.caption(f"Copertura dati (Data Pagamento): dal **{stats['data_min']}** al **{stats['data_max']}**.")
else:
    st.caption("Nessun dato ancora caricato.")

st.divider()
st.subheader("🕒 Storico caricamenti")
log = db.get_upload_log(conn)
st.dataframe(log, hide_index=True, use_container_width=True)

with st.expander("⚠️ Zona pericolosa"):
    st.warning(
        "Il DB è un file SQLite locale (`data/ecombi.db`). Su Streamlit Community Cloud "
        "persiste finché l'app resta attiva/in sospensione, ma viene **azzerato ad ogni "
        "redeploy**. Fanne un backup periodico se contiene dati che non vuoi ricaricare da capo."
    )
    conferma = st.checkbox("Ho capito, voglio svuotare completamente il DB")
    if st.button("🗑️ Svuota DB", disabled=not conferma):
        conn.executescript("DELETE FROM righe; DELETE FROM log_match; DELETE FROM upload_log;")
        conn.commit()
        st.success("DB svuotato.")
        st.rerun()
