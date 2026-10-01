import datetime as dt

import streamlit as st

from core import db, engine, pipeline as pl
from core.ui_helpers import shift_year

st.set_page_config(page_title="Carica Dati", page_icon="⬆️", layout="wide")
st.title("⬆️ Carica Dati — pannello di controllo")

st.caption(
    "Da qui passa tutto il ciclo dati: **1️⃣** scegli periodo e perimetro e premi **Genera "
    "dati report** (vale per tutte le pagine, finché non lo rigeneri); **2️⃣** carica i file "
    "DATASET e RESI (CSV o TXT) man mano che arrivano; **3️⃣** controlla stato e storico del DB."
)

conn = db.connect()
stats = db.get_stats(conn)
db_vuoto = stats["righe_totali"] == 0

# =========================================================================================
# 1️⃣ Periodo di analisi + perimetro → Genera dati report (vale per tutte le pagine)
# =========================================================================================
st.header("1️⃣ Periodo di analisi e perimetro")

if db_vuoto:
    st.info(
        "Il DB è vuoto: carica almeno un file DATASET nella sezione **2️⃣ Caricamento file** "
        "qui sotto, poi torna in questa sezione per generare i report."
    )
else:
    data_min = dt.date.fromisoformat(stats["data_min"])
    data_max = dt.date.fromisoformat(stats["data_max"])
    st.caption(
        f"Copertura dati nel DB (Data Pagamento): dal **{stats['data_min']}** al **{stats['data_max']}**."
    )

    col_periodi, col_pulsanti, col_vuota = st.columns([2, 2, 2])

    with col_periodi:
        perimetro_label = st.radio(
            "Perimetro logistico",
            ["TOTALE (Diretti + Logistica Esterna)", "SOLO DIRETTI", "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)"],
            index=0,
        )
        perimetro = {"TOTALE (Diretti + Logistica Esterna)": "1", "SOLO DIRETTI": "2",
                     "SOLO LOGISTICA ESTERNA (ZFS/FBA/AMZ)": "3"}[perimetro_label]

        periodo_a = st.date_input(
            "Periodo corrente",
            value=(max(data_min, shift_year(data_max, -1)), data_max),
            min_value=data_min, max_value=data_max, key="periodo_a",
        )
        # Confronto AUTOMATICO anno−1 (clampato alla copertura del DB);
        # l'anno−2 è opzionale e si attiva con la spunta qui sotto.
        periodo_a_ok = isinstance(periodo_a, tuple) and len(periodo_a) == 2
        periodo_b = None
        confronta_2anni = False
        if periodo_a_ok:
            b0 = max(data_min, shift_year(periodo_a[0], -1))
            b1 = min(data_max, shift_year(periodo_a[1], -1))
            if b0 <= b1:
                periodo_b = (b0, b1)
            st.caption(
                f"Confronto automatico — Anno−1: **{periodo_b[0]} → {periodo_b[1]}**"
                if periodo_b else
                "Confronto automatico — Anno−1: non coperto dal DB (niente dati da confrontare)."
            )
            confronta_2anni = st.checkbox("Confronta anche 2 anni precedenti", value=False)
            if confronta_2anni:
                c0 = max(data_min, shift_year(periodo_a[0], -2))
                c1 = min(data_max, shift_year(periodo_a[1], -2))
                st.caption(
                    f"Confronto Anno−2: **{c0} → {c1}**"
                    if c0 <= c1 else
                    "Confronto Anno−2: non coperto dal DB (le pagine lo mostreranno vuoto)."
                )

    with col_pulsanti:
        with st.expander("🖼️ Anagrafica articoli (facoltativa)"):
            st.caption("Serve per descrizioni, serie, classificazione per genere (Taglie) e foto. Vale per tutta la sessione.")
            anagrafica_file = st.file_uploader("ANAGRAFICA", type=["csv", "txt"], key="anag_home")
            if anagrafica_file is not None:
                st.session_state["anagrafica_file"] = anagrafica_file

        genera = st.button(
            "▶️ Genera dati report", type="primary", use_container_width=True,
            disabled=not periodo_a_ok,
        )

        if genera:
            anagrafica = (
                engine.load_anagrafica(st.session_state["anagrafica_file"])
                if st.session_state.get("anagrafica_file") else {}
            )
            with st.spinner("Interrogazione DB…"):
                try:
                    result = pl.build_pipeline_from_db(
                        conn,
                        periodo_current=periodo_a,
                        periodo_old=periodo_b,
                        perimetro=perimetro,
                        anagrafica=anagrafica,
                    )
                    st.session_state["pipeline"] = result
                    st.session_state["perimetro_label"] = perimetro_label
                    st.session_state["sel_periodo_a"] = periodo_a
                    st.session_state["sel_periodo_b"] = periodo_b
                    st.session_state["periodo_a_label"] = f"{periodo_a[0]} → {periodo_a[1]}"
                    st.session_state["periodo_b_label"] = (
                        f"{periodo_b[0]} → {periodo_b[1]}" if periodo_b else None
                    )
                    st.session_state["sel_confronta_2anni"] = confronta_2anni
                except Exception as e:
                    st.exception(e)
                    st.stop()

pipe = st.session_state.get("pipeline")
if pipe is not None:
    st.success(
        f"✅ Dati pronti — periodo corrente **{st.session_state['periodo_a_label']}**"
        + (
            f", confronto **{st.session_state['periodo_b_label']}**"
            if st.session_state.get("periodo_b_label") else ""
        )
        + ". Naviga tra i report dal menu a sinistra."
    )
    m1, m2, m3 = st.columns(3)
    m1.metric("Righe periodo corrente", f"{len(pipe.current_data):,}".replace(",", "."))
    m2.metric("Righe periodo confronto", f"{len(pipe.old_data):,}".replace(",", "."))
    m3.metric("Rimborsi extra nel periodo", f"{len(pipe.esito_resi_current['standalone']):,}".replace(",", "."))
    st.caption(
        "“Rimborsi extra” = ordini rimborsati nel periodo corrente ma spediti prima (o senza "
        "spedito noto): riducono il fatturato netto reale del periodo pur non essendo "
        "conteggiati come vendita del periodo stesso."
    )

st.divider()
st.header("2️⃣ Caricamento file DATASET e RESI")
st.caption(
    "Il DB è incrementale: ogni file viene elaborato una volta e ricaricare lo stesso file "
    "non crea duplicati. I RESI aggiornano lo stato delle righe DATASET già presenti "
    "(Spedito→Reso) senza toccare il loro numero ordine."
)


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
st.header("3️⃣ Stato del DB")
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
st.header("4️⃣ Storico caricamenti")
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
