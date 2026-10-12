import importlib
from datetime import datetime, timezone
import streamlit as st

from core import db, engine
# Ricarica dinamica per sincronizzare modifiche a caldo nel processo Streamlit
importlib.reload(db)
importlib.reload(engine)

from core.design_system import page_setup

page_setup("Carica Dati", "⬆️",
           "Carica i file DATASET e RESI (CSV) e controlla stato e storico del DB — "
           "periodo e perimetro dei report si scelgono nella barra in alto")

conn = db.connect()

# L'ANAGRAFICA nel DB: descrizioni, serie, brand, genere (Taglie) e foto.
anag_stats = db.get_anagrafica_stats(conn)
with st.expander("🖼️ Anagrafica articoli nel DB", expanded=anag_stats["totale_sku13"] == 0):
    st.caption(
        "Salva e aggiorna l'anagrafica articoli nel database SQLite (supporta file multipli come anagrafica_261.csv, anagrafica_262.csv). "
        "Gli articoli già presenti vengono aggiornati e sostituiti con i dati più recenti."
    )
    try:
        st.page_link("pages/15_Anagrafica.py", label="👉 Vai alla pagina dedicata: Gestione Anagrafica, Regole di Esclusione e Stagioni", icon="📋")
    except Exception:
        pass
    anagrafica_files = st.file_uploader(
        "Uno o più file ANAGRAFICA (TSV/CSV)", type=["csv", "tsv", "txt"],
        accept_multiple_files=True, key="anag_files"
    )
    c_btn1, c_btn2, c_btn3 = st.columns([1.2, 1.2, 1.2])
    with c_btn1:
        carica_anag = st.button("Salva ANAGRAFICA nel DB", disabled=not anagrafica_files, width="stretch")
    with c_btn2:
        sinc_gen = st.button(
            "Sincronizza Genere sulle Vendite", disabled=anag_stats["totale_sku13"] == 0, width="stretch",
            help="Aggiorna la colonna genere sulle righe del DB in base all'anagrafica"
        )
    with c_btn3:
        with st.popover("🗑️ Elimina solo Anagrafica", disabled=anag_stats["totale_sku13"] == 0, width="stretch"):
            st.warning("Stai per cancellare l'intera tabella anagrafica dal DB.")
            st.caption("I dati delle vendite e dei resi NON verranno toccati.")
            if st.button("Conferma eliminazione", type="primary", width="stretch", key="btn_conf_del_anag"):
                if hasattr(db, "svuota_anagrafica"):
                    db.svuota_anagrafica(conn)
                else:
                    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
                    conn.execute("DELETE FROM anagrafica;")
                    conn.execute(
                        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, convertiti, duplicati, standalone) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (now, "SVUOTA_ANAGRAFICA", "ANAGRAFICA", 0, 0, 0, 0, 0, 0),
                    )
                    conn.commit()
                st.session_state.pop("anagrafica", None)
                st.session_state["rigenera_pipeline"] = True
                st.success("Anagrafica eliminata con successo dal DB.")
                st.rerun()

    if carica_anag and anagrafica_files:
        for f in anagrafica_files:
            sbox = st.status(f"Importazione **{f.name}**…", expanded=True)
            try:
                sbox.write("Parsing dati anagrafica…")
                records = engine.parse_anagrafica(f, fonte_file=f.name)
                sbox.write(f"Scrittura nel DB ({len(records):,} righe)…".replace(",", "."))
                res = db.upsert_anagrafica(conn, records, fonte_file=f.name)
                sbox.update(label=f"✅ {f.name}", state="complete")
                msg_escl = f"🚫 **{res['righe_escluse']:,}** escluse dalle regole, " if res.get("righe_escluse") else ""
                st.success(
                    f"**{f.name}** — {res['righe_nel_file']:,} righe: "
                    f"**{res['righe_nuove']:,}** nuove varianti inserite, "
                    f"**{res['righe_aggiornate']:,}** articoli esistenti aggiornati/sostituiti, "
                    f"{msg_escl}"
                    f"Totale articoli in anagrafica: **{res['totale_articoli']:,}**."
                    .replace(",", ".")
                )
            except Exception as e:
                sbox.update(label=f"❌ {f.name} — errore", state="error")
                st.exception(e)

        n_agg = db.sincronizza_genere_righe(conn)
        if n_agg > 0:
            st.info(f"👟 Sincronizzato genere su **{n_agg:,}** righe vendite/resi nel DB.".replace(",", "."))
        st.session_state["anagrafica"] = db.get_anagrafica_dict(conn)
        st.session_state["rigenera_pipeline"] = True
        st.rerun()

    if sinc_gen:
        n_agg = db.sincronizza_genere_righe(conn)
        st.success(f"👟 Sincronizzato genere su **{n_agg:,}** righe vendite/resi nel DB.".replace(",", "."))
        st.session_state["rigenera_pipeline"] = True

    if anag_stats["totale_sku13"] > 0:
        c_a1, c_a2, c_a3 = st.columns(3)
        c_a1.metric("Varianti SKU13", f"{anag_stats['totale_sku13']:,}".replace(",", "."))
        c_a2.metric("Modelli SKU7", f"{anag_stats['totale_sku7']:,}".replace(",", "."))
        fonti_str = ", ".join(anag_stats["fonti_file"]) if anag_stats["fonti_file"] else "—"
        c_a3.caption(f"Fonti caricate: **{fonti_str}**\n\nUltimo agg.: **{anag_stats['ultimo_aggiornamento'] or '—'}**")

st.header("1️⃣ Caricamento file DATASET e RESI")
st.caption(
    "Il DB è incrementale: ogni file viene elaborato una volta e ricaricare lo stesso file "
    "non crea duplicati. I RESI aggiornano lo stato delle righe DATASET già presenti "
    "(Spedito→Reso) senza toccare il loro numero ordine."
)


def _process_and_show(files, tipo: str):
    if not files:
        return
    anagrafica = st.session_state.get("anagrafica") or db.get_anagrafica_dict(conn)
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
                msg_escl_ds = f", {stats['righe_escluse']:,} escluse dalle regole" if stats.get("righe_escluse") else ""
                st.success(
                    f"**{f.name}** — {stats['righe_nel_file']:,} righe nel file: "
                    f"{stats['righe_nuove']:,} nuove, {stats['righe_gia_presenti']:,} già presenti (ignorate)"
                    f"{msg_escl_ds}."
                    .replace(",", ".")
                )
            else:
                status_box.write("Ricerca corrispondenze e scrittura nel DB…")
                stats = db.upsert_resi(conn, processed, f.name, progress=on_progress)
                status_box.update(label=f"✅ {f.name}", state="complete")
                msg_escl_resi = f", {stats['righe_escluse']:,} escluse dalle regole" if stats.get("righe_escluse") else ""
                st.success(
                    f"**{f.name}** — {len(processed):,} righe nel file: "
                    f"{stats['convertiti']:,} convertite Spedito→Reso, "
                    f"{stats['duplicati']:,} già riconciliate (scartate), "
                    f"{stats['senza_ordine']:,} resi caricati prima del loro ordine (trattati come ordini reali, con le loro date)"
                    f"{msg_escl_resi}."
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
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Righe totali", f"{stats['righe_totali']:,}".replace(",", "."))
c2.metric("Spedite", f"{stats['spediti']:,}".replace(",", "."))
c3.metric("Rese", f"{stats['resi']:,}".replace(",", "."))
c4.metric("Resi senza ordine", f"{stats['resi_senza_ordine']:,}".replace(",", "."))
c5.metric("Anagrafica SKU", f"{stats.get('anagrafica_totale', 0):,}".replace(",", "."))
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
    svuota_anag = st.checkbox("Includi anche l'Anagrafica nello svuotamento", value=True)
    conferma = st.checkbox("Ho capito, voglio svuotare completamente il DB")
    if st.button("🗑️ Svuota DB", disabled=not conferma):
        script = "DELETE FROM righe; DELETE FROM log_match; DELETE FROM upload_log;"
        if svuota_anag:
            script += " DELETE FROM anagrafica;"
        conn.executescript(script)
        conn.commit()
        st.session_state.pop("anagrafica", None)
        st.session_state["rigenera_pipeline"] = True
        st.success("DB svuotato.")
        st.rerun()
