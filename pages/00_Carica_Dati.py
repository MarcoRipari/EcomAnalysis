import streamlit as st

from core import db, engine
from core.design_system import page_setup

page_setup("Carica Dati", "⬆️",
           "Carica i file DATASET e RESI (CSV) e controlla stato e storico del DB — "
           "periodo e perimetro dei report si scelgono nella barra in alto")

conn = db.connect()

# L'ANAGRAFICA (facoltativa) vale per tutta la sessione: descrizioni, serie, genere (Taglie) e foto.
with st.expander("🖼️ Anagrafica articoli (facoltativa)"):
    st.caption("Serve per descrizioni, serie, classificazione per genere (Taglie) e foto. Il periodo si sceglie "
               "nella barra in alto.")
    anagrafica_file = st.file_uploader("ANAGRAFICA", type=["csv"], key="anag_home")
    if anagrafica_file is not None:
        firma = (anagrafica_file.name, anagrafica_file.size)
        if st.session_state.get("anagrafica_firma") != firma:
            anagrafica_file.seek(0)
            st.session_state["anagrafica"] = engine.load_anagrafica(anagrafica_file)
            st.session_state["anagrafica_firma"] = firma
            st.session_state["rigenera_pipeline"] = True      # la barra periodo ricalcola i dati
            st.rerun()
    if st.session_state.get("anagrafica"):
        st.caption(f"Anagrafica caricata: {len(st.session_state['anagrafica']):,} voci.".replace(",", "."))

st.header("1️⃣ Caricamento file DATASET e RESI")
st.caption(
    "Il DB è incrementale: ogni file viene elaborato una volta e ricaricare lo stesso file "
    "non crea duplicati. I RESI aggiornano lo stato delle righe DATASET già presenti "
    "(Spedito→Reso) senza toccare il loro numero ordine."
)


def _process_and_show(files, tipo: str):
    if not files:
        return
    anagrafica = st.session_state.get("anagrafica", {})
    for f in files:
        status_box = st.status(f"Elaborazione **{f.name}**…", expanded=True)
        try:
            status_box.write("Lettura file…")
            raw = engine.read_raw_csv(f)
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
                    f"{stats['senza_ordine']:,} resi caricati prima del loro ordine (trattati come ordini reali, con le loro date)."
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
    dataset_files = st.file_uploader("Uno o più file DATASET", type=["csv"],
                                      accept_multiple_files=True, key="up_dataset")
    if st.button("Carica DATASET nel DB", disabled=not dataset_files, width="stretch"):
        _process_and_show(dataset_files, "DATASET")

with col2:
    st.subheader("↩️ File RESI")
    resi_files = st.file_uploader("Uno o più file RESI", type=["csv"],
                                   accept_multiple_files=True, key="up_resi")
    if st.button("Carica RESI nel DB", disabled=not resi_files, width="stretch"):
        _process_and_show(resi_files, "RESI")

st.divider()
st.header("2️⃣ Stato del DB")
stats = db.get_stats(conn)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Righe totali", f"{stats['righe_totali']:,}".replace(",", "."))
c2.metric("Spedite", f"{stats['spediti']:,}".replace(",", "."))
c3.metric("Rese", f"{stats['resi']:,}".replace(",", "."))
c4.metric("Resi senza ordine nel DB", f"{stats['resi_senza_ordine']:,}".replace(",", "."))
if stats["data_min"]:
    st.caption(f"Copertura dati (Data Pagamento): dal **{stats['data_min']}** al **{stats['data_max']}**.")
else:
    st.caption("Nessun dato ancora caricato.")

st.divider()
st.header("3️⃣ Storico caricamenti")
log = db.get_upload_log(conn)
st.dataframe(log, hide_index=True, width="stretch")

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
