import importlib
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

from core import db, engine
importlib.reload(db)
importlib.reload(engine)

from core.design_system import page_setup, section, metric_cards, data_table, empty_state
from core.formatting import fmt_int

page_setup("Anagrafica Articoli", None)

conn = db.connect()

# ---------------------------------------------------------------------------------------
# Caricamento statistiche e stato attuale
# ---------------------------------------------------------------------------------------
stats = db.get_anagrafica_stats(conn)
tot_sku13 = stats.get("totale_sku13", 0)
tot_sku7 = stats.get("totale_sku7", 0)
per_brand = stats.get("per_brand", {})
per_genere = stats.get("per_genere", {})

regole_attive = db.get_regole_anagrafica(conn)
esclusioni = db.get_esclusioni_anagrafica(conn)

nc_count = per_genere.get("NON CLASSIFICATO", 0)
copertura_genere_pct = ((tot_sku13 - nc_count) / tot_sku13 * 100) if tot_sku13 > 0 else 0.0

# KPI in cima alla pagina
metric_cards([
    {"label": "Articoli (SKU13)", "value": fmt_int(tot_sku13)},
    {"label": "Modelli Unici (SKU7)", "value": fmt_int(tot_sku7)},
    {"label": "Marchi a Catalogo", "value": fmt_int(len(per_brand))},
    {
        "label": "Copertura Genere",
        "value": f"{copertura_genere_pct:.1f}%",
        "delta": f"{fmt_int(nc_count)} non class." if nc_count > 0 else "100% classificati",
        "delta_good": nc_count == 0,
    },
    {"label": "Regole di Esclusione", "value": f"{len([r for r in regole_attive if r['attivo']])} attive"},
])

st.write("")

# ---------------------------------------------------------------------------------------
# Tab principali di gestione Anagrafica
# ---------------------------------------------------------------------------------------
tab_esplora, tab_regole, tab_genere, tab_stagione, tab_import = st.tabs([
    "Catalogo Articoli",
    "Regole Esclusione",
    "Classificazione Genere",
    "Modifica Stagione",
    "Import & Manutenzione",
])

# =======================================================================================
# TAB 1: ESPLORA & CERCA
# =======================================================================================
with tab_esplora:
    section("Catalogo Anagrafica Articoli")

    if tot_sku13 == 0:
        empty_state("Nessun articolo presente nell'anagrafica del DB. Vai al tab 'Import & Manutenzione DB' per caricare i file.")
    else:
        # Filtri orizzontali
        c_f1, c_f2, c_f3, c_f4 = st.columns([2, 1.5, 1.5, 1.5])
        with c_f1:
            q_text = st.text_input("🔍 Cerca testo (SKU, modello, descrizione)", placeholder="es. 0503354 o LIVYA", key="anag_q")
        with c_f2:
            opzioni_brand = ["Tutti i Marchi"] + sorted(list(per_brand.keys()))
            sel_brand = st.selectbox("Marchio", opzioni_brand, key="anag_sel_brand")
        with c_f3:
            opzioni_genere = ["Tutti i Generi"] + sorted(list(per_genere.keys()))
            sel_genere = st.selectbox("Genere", opzioni_genere, key="anag_sel_genere")
        with c_f4:
            # Query stagioni uniche complete (anno/stagione es. 2026/1, 2026/2)
            stag_expr = "CASE WHEN semestre IS NOT NULL AND semestre != '' THEN stagione || '/' || semestre ELSE stagione END"
            stagioni_db = [
                r[0] for r in conn.execute(
                    f"SELECT DISTINCT {stag_expr} AS stag_full FROM anagrafica WHERE stagione IS NOT NULL AND stagione != '' ORDER BY stag_full DESC"
                ).fetchall() if r[0]
            ]
            opzioni_stag = ["Tutte le Stagioni"] + stagioni_db
            sel_stag = st.selectbox("Stagione", opzioni_stag, key="anag_sel_stag")

        c_chk1, c_chk2 = st.columns([1, 1])
        with c_chk1:
            solo_nc = st.checkbox("Mostra solo articoli NON CLASSIFICATI", key="anag_chk_nc")
        with c_chk2:
            solo_esclusi = st.checkbox("Mostra solo articoli ESCLUSI dalle regole", key="anag_chk_escl")

        # Costruzione query con filtri
        where_clauses = ["1=1"]
        params = []

        if q_text.strip():
            qt = f"%{q_text.strip()}%"
            where_clauses.append("(sku13 LIKE ? OR sku7 LIKE ? OR brand LIKE ? OR descrizione LIKE ?)")
            params.extend([qt, qt, qt, qt])

        if sel_brand != "Tutti i Marchi":
            where_clauses.append("brand = ?")
            params.append(sel_brand)

        if sel_genere != "Tutti i Generi":
            where_clauses.append("genere = ?")
            params.append(sel_genere)

        if sel_stag != "Tutte le Stagioni":
            if "/" in sel_stag:
                stag_p, sem_p = sel_stag.split("/", 1)
                where_clauses.append("stagione = ? AND semestre = ?")
                params.extend([stag_p.strip(), sem_p.strip()])
            else:
                where_clauses.append("stagione = ?")
                params.append(sel_stag)

        if solo_nc:
            where_clauses.append("(genere = 'NON CLASSIFICATO' OR genere = '' OR genere IS NULL)")

        sql_base = f"""
            SELECT sku13, sku7, brand, linea, categoria, descrizione, taglia_base,
                   {stag_expr} AS stagione, genere, fonte_file, aggiornato_il
            FROM anagrafica
            WHERE {" AND ".join(where_clauses)}
            ORDER BY sku7 ASC, sku13 ASC
            LIMIT 500
        """
        df_view = pd.read_sql_query(sql_base, conn, params=params)

        # Flag escluso
        marchi_escl = esclusioni["marchi"]
        cat_escl = esclusioni["categorie"]
        df_view["Escluso"] = df_view.apply(
            lambda r: "SÌ" if (str(r["brand"]).upper().strip() in marchi_escl or str(r["categoria"]).strip() in cat_escl) else "NO",
            axis=1
        )

        if solo_esclusi:
            df_view = df_view[df_view["Escluso"] == "SÌ"].reset_index(drop=True)

        st.caption(f"Visualizzati **{len(df_view):,}** articoli (limite max 500 per vista).".replace(",", "."))

        # Configurazione colonne tabella
        col_cfg = {
            "sku13": st.column_config.TextColumn("SKU 13", width="small"),
            "sku7": st.column_config.TextColumn("SKU 7", width="small"),
            "brand": st.column_config.TextColumn("Marchio", width="medium"),
            "linea": st.column_config.TextColumn("Linea / Serie", width="medium"),
            "categoria": st.column_config.TextColumn("Cat.", width="small"),
            "descrizione": st.column_config.TextColumn("Descrizione", width="large"),
            "taglia_base": st.column_config.TextColumn("Tg Base", width="small"),
            "stagione": st.column_config.TextColumn("Stagione", width="small"),
            "genere": st.column_config.TextColumn("Genere", width="medium"),
            "Escluso": st.column_config.TextColumn("Escluso?", width="small"),
            "fonte_file": st.column_config.TextColumn("File Fonte", width="medium"),
            "aggiornato_il": st.column_config.TextColumn("Aggiornato Il", width="medium"),
        }
        data_table(df_view, col_cfg, key="dt_anag_view")

        # Download CSV
        csv_bytes = df_view.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            "📥 Scarica risultati in CSV",
            data=csv_bytes,
            file_name="estratto_anagrafica.csv",
            mime="text/csv",
        )


# =======================================================================================
# TAB 2: REGOLE DI ESCLUSIONE
# =======================================================================================
with tab_regole:
    section("Regole di Esclusione (Marchi e Categorie)",
            caption="Escludi determinati marchi o codici categoria (ad es. la categoria '003' per semilavorati/tomaie). "
                    "Gli articoli esclusi vengono etichettati e possono essere filtrati dai report.")

    c_r1, c_r2 = st.columns([1, 1])

    with c_r1:
        st.markdown("##### 🚫 Escludi Marchio")
        st.caption("Seleziona uno o più marchi da escludere.")
        brand_disponibili = sorted(list(per_brand.keys()))
        marchi_attualmente_esclusi = sorted(list(esclusioni["marchi"]))
        sel_marchi_add = st.multiselect(
            "Marchi da escludere",
            options=brand_disponibili,
            default=[b for b in brand_disponibili if b.upper() in marchi_attualmente_esclusi],
            key="ms_escl_marchi"
        )
        note_brand = st.text_input("Nota / Motivo esclusione marchio", placeholder="es. Linea non gestita o licenza esterna", key="note_escl_brand")
        if st.button("Aggiorna Esclusioni Marchi", type="primary", key="btn_salva_escl_brand"):
            # Rimuove marchi deselezionati e inserisce quelli selezionati
            for b in brand_disponibili:
                if b in sel_marchi_add:
                    db.salva_regola_anagrafica(conn, "escludi_marchio", b, attivo=1, note=note_brand)
                else:
                    # Se era presente, lo disattiviamo o eliminiamo
                    cur = conn.cursor()
                    cur.execute("DELETE FROM regole_anagrafica WHERE tipo = 'escludi_marchio' AND valore = ?", (b,))
            conn.commit()
            n_del = db.elimina_articoli_esclusi_anagrafica(conn)
            st.session_state.pop("anagrafica", None)
            st.session_state["rigenera_pipeline"] = True
            msg = "Regole sui marchi aggiornate!"
            if n_del > 0:
                msg += f" Rimossi {fmt_int(n_del)} articoli esclusi già presenti nel DB."
            st.success(msg)
            st.rerun()

    with c_r2:
        st.markdown("##### 🚫 Escludi Categoria")
        st.caption("Seleziona categorie specifiche (es. 003 = Tomaie / Campionari).")
        # Elenco categorie presenti nel DB con conteggio
        cat_db = conn.execute("SELECT categoria, COUNT(*) FROM anagrafica GROUP BY categoria ORDER BY COUNT(*) DESC").fetchall()
        opzioni_cat_labels = {r[0]: f"{r[0]} ({r[1]:,} articoli)".replace(",", ".") for r in cat_db if r[0]}
        cat_attualmente_escluse = sorted(list(esclusioni["categorie"]))

        sel_cat_add = st.multiselect(
            "Categorie da escludere",
            options=list(opzioni_cat_labels.keys()),
            default=[c for c in opzioni_cat_labels.keys() if c in cat_attualmente_escluse],
            format_func=lambda c: opzioni_cat_labels.get(c, c),
            key="ms_escl_cat"
        )
        note_cat = st.text_input("Nota / Motivo esclusione categoria", placeholder="es. Semilavorati tomaie non commerciali", key="note_escl_cat")
        if st.button("Aggiorna Esclusioni Categorie", type="primary", key="btn_salva_escl_cat"):
            for c in opzioni_cat_labels.keys():
                if c in sel_cat_add:
                    db.salva_regola_anagrafica(conn, "escludi_categoria", c, attivo=1, note=note_cat)
                else:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM regole_anagrafica WHERE tipo = 'escludi_categoria' AND valore = ?", (c,))
            conn.commit()
            n_del = db.elimina_articoli_esclusi_anagrafica(conn)
            st.session_state.pop("anagrafica", None)
            st.session_state["rigenera_pipeline"] = True
            msg = "Regole sulle categorie aggiornate!"
            if n_del > 0:
                msg += f" Rimossi {fmt_int(n_del)} articoli esclusi già presenti nel DB."
            st.success(msg)
            st.rerun()

    st.divider()
    section("Riepilogo Regole Attive nel Database")
    regole_correnti = db.get_regole_anagrafica(conn)
    if not regole_correnti:
        empty_state("Nessuna regola di esclusione impostata. Tutti gli articoli sono attualmente inclusi.")
    else:
        righe_regole = []
        for r in regole_correnti:
            tipo_label = "Marchio" if r["tipo"] == "escludi_marchio" else "Categoria"
            # Calcolo impatto su anagrafica
            if r["tipo"] == "escludi_marchio":
                c_imp = conn.execute("SELECT COUNT(*) FROM anagrafica WHERE brand = ?", (r["valore"],)).fetchone()[0]
            else:
                c_imp = conn.execute("SELECT COUNT(*) FROM anagrafica WHERE categoria = ?", (r["valore"],)).fetchone()[0]
            righe_regole.append({
                "ID": r["id"],
                "Tipo Regola": tipo_label,
                "Valore Escluso": r["valore"],
                "Articoli Impattati": fmt_int(c_imp),
                "Attiva": "SÌ" if r["attivo"] else "NO",
                "Note": r["note"],
                "Creata il": r["creato_il"],
            })
        df_regole = pd.DataFrame(righe_regole)
        data_table(df_regole, key="dt_regole_anag")

        n_attualmente_esclusi = db.conta_articoli_esclusi_anagrafica(conn)
        if n_attualmente_esclusi > 0:
            st.warning(f"⚠️ Nel database sono attualmente presenti **{fmt_int(n_attualmente_esclusi)}** articoli che violano le regole di esclusione attive.")
            if st.button("🗑️ Rimuovi articoli esclusi attualmente nel DB", type="primary", key="btn_del_all_escl"):
                n_del = db.elimina_articoli_esclusi_anagrafica(conn)
                st.session_state.pop("anagrafica", None)
                st.session_state["rigenera_pipeline"] = True
                st.success(f"✅ Rimossi {fmt_int(n_del)} articoli esclusi dal database.")
                st.rerun()

        c_del_r1, c_del_r2 = st.columns([2, 2])
        with c_del_r1:
            id_da_eliminare = st.selectbox("Seleziona regola da rimuovere", options=[r["id"] for r in regole_correnti], format_func=lambda x: f"Regola #{x}", key="sel_reg_del")
        with c_del_r2:
            st.write("")
            st.write("")
            if st.button("🗑️ Rimuovi regola selezionata", key="btn_del_single_reg"):
                db.elimina_regola_anagrafica(conn, id_da_eliminare)
                st.success(f"Regola #{id_da_eliminare} eliminata con successo.")
                st.rerun()


# =======================================================================================
# TAB 3: VERIFICA & GESTIONE GENERE
# =======================================================================================
with tab_genere:
    section("Verifica Copertura Genere e Riclassificazione Automatica",
            caption="Controlla se ci sono SKU senza genere assegnato o 'NON CLASSIFICATO' e correggili con euristiche avanzate o manualmente.")

    c_g1, c_g2, c_g3 = st.columns([1.5, 1.2, 1.3])
    with c_g1:
        if nc_count == 0:
            st.success("✅ **Perfetto!** Tutti gli articoli in anagrafica hanno un genere commerciale assegnato.")
        else:
            st.warning(f"⚠️ Ci sono **{fmt_int(nc_count)}** articoli su {fmt_int(tot_sku13)} con genere **NON CLASSIFICATO** ({nc_count/tot_sku13*100:.1f}%).")
    with c_g2:
        btn_ricalcola = st.button("⚡ Ricalcola Generi Automaticamente", type="primary", disabled=nc_count == 0, width="stretch",
                                 help="Applica le regole avanzate (Kids, Child, New Born, Licenze Falc, Tomaie donna) per riclassificare gli articoli non assegnati")
    with c_g3:
        btn_sinc_gen = st.button("🔄 Sincronizza Genere sulle Vendite", width="stretch",
                                 help="Propaga il genere dall'anagrafica a tutte le righe di vendite e resi nel DB")

    if btn_ricalcola:
        with st.spinner("Ricalcolo genere in corso con euristiche avanzate…"):
            res_ric = db.ricalcola_tutti_generi(conn, solo_non_classificati=True)
            # Sincronizza anche le vendite
            n_vendite = db.sincronizza_genere_righe(conn)
            st.session_state.pop("anagrafica", None)
            st.session_state["rigenera_pipeline"] = True
            msg = (
                f"✅ **Ricalcolo completato!** {res_ric['aggiornati']:,} articoli riclassificati con successo su {res_ric['valutati']:,} valutati.\n"
                f"- Righe vendite/resi aggiornate nel DB: **{n_vendite:,}**\n"
                f"- Dettaglio per nuovo genere: {res_ric['per_genere']}"
            ).replace(",", ".")
            st.success(msg)
            st.rerun()

    if btn_sinc_gen:
        with st.spinner("Sincronizzazione sulle righe vendite del DB…"):
            n_up = db.sincronizza_genere_righe(conn)
            st.session_state["rigenera_pipeline"] = True
            st.success(f"✅ Sincronizzazione completata: **{n_up:,}** righe di vendita/reso aggiornate nel database.".replace(",", "."))
            st.rerun()

    st.divider()

    # Tabella degli SKU attualmente non classificati
    section("Articoli Attualmente NON CLASSIFICATI",
            caption="Visualizza l'elenco degli articoli che non hanno ancora un genere commerciale assegnato.")

    stag_expr = "CASE WHEN semestre IS NOT NULL AND semestre != '' THEN stagione || '/' || semestre ELSE stagione END"
    sql_nc = f"""
        SELECT sku13, sku7, brand, linea, categoria, descrizione, taglia_base,
               {stag_expr} AS stagione
        FROM anagrafica
        WHERE genere = 'NON CLASSIFICATO' OR genere = '' OR genere IS NULL
        ORDER BY brand ASC, sku7 ASC
        LIMIT 300
    """
    df_nc = pd.read_sql_query(sql_nc, conn)

    if df_nc.empty:
        empty_state("Nessun articolo non classificato! La copertura del genere è al 100%.", icon="🎉")
    else:
        st.caption(f"Trovati **{len(df_nc):,}** articoli senza genere assegnato (mostrati fino a 300).".replace(",", "."))
        col_nc_cfg = {
            "sku13": st.column_config.TextColumn("SKU 13"),
            "sku7": st.column_config.TextColumn("SKU 7"),
            "brand": st.column_config.TextColumn("Marchio"),
            "linea": st.column_config.TextColumn("Linea"),
            "categoria": st.column_config.TextColumn("Cat"),
            "descrizione": st.column_config.TextColumn("Descrizione"),
            "taglia_base": st.column_config.TextColumn("Tg Base"),
            "stagione": st.column_config.TextColumn("Stagione"),
        }
        data_table(df_nc, col_nc_cfg, key="dt_nc_anag")

        # Form di correzione manuale mirata
        st.write("")
        section("Assegnazione Manuale Genere", caption="Assegna direttamente il genere a uno specifico SKU o a tutte le varianti di un modello.")
        c_m1, c_m2, c_m3 = st.columns([1.5, 1.5, 1])
        with c_m1:
            sku_target_gen = st.text_input("SKU13 o SKU7 da correggere", placeholder="es. 0503354", key="txt_sku_corr_gen")
        with c_m2:
            nuovo_gen_sel = st.selectbox(
                "Nuovo Genere",
                ["BAMBINO", "DONNA", "UOMO", "UNISEX", "ACCESSORI", "ABBIGLIAMENTO"],
                key="sel_nuovo_gen"
            )
        with c_m3:
            st.write("")
            st.write("")
            btn_applica_gen = st.button("Salva Genere", type="primary", key="btn_salva_gen_man")

        if btn_applica_gen and sku_target_gen.strip():
            clean_sku = sku_target_gen.strip()
            # Se lungo 7 caratteri aggiorna per sku7, altrimenti per sku13
            is_sku7 = len(clean_sku) == 7
            n_mod = db.aggiorna_genere_anagrafica(conn, clean_sku, nuovo_gen_sel, aggiorna_sku7=is_sku7)
            if n_mod > 0:
                db.sincronizza_genere_righe(conn)
                st.session_state.pop("anagrafica", None)
                st.session_state["rigenera_pipeline"] = True
                st.success(f"✅ Genere aggiornato per **{n_mod}** articoli in anagrafica!")
                st.rerun()
            else:
                st.error(f"Nessun articolo trovato con codice '{clean_sku}'.")


# =======================================================================================
# TAB 4: MODIFICA STAGIONE SKU
# =======================================================================================
with tab_stagione:
    section("Modifica Stagione per Singolo SKU",
            caption="Cerca un codice articolo (SKU13 o SKU7) e modifica la stagione registrata nell'anagrafica.")

    c_s1, c_s2 = st.columns([2.5, 1])
    with c_s1:
        cerca_sku_stag = st.text_input("Inserisci SKU 13 o SKU 7", placeholder="es. 0503354010000 oppure 0503354", key="txt_cerca_sku_stag")
    with c_s2:
        st.write("")
        st.write("")
        cerca_btn = st.button("🔎 Cerca Articolo", key="btn_cerca_sku_stag")

    target_sku_query = cerca_sku_stag.strip()
    if target_sku_query:
        item = db.get_dettaglio_sku_anagrafica(conn, target_sku_query)
        if not item:
            st.warning(f"Nessun articolo trovato in anagrafica per il codice **'{target_sku_query}'**.")
        else:
            st.markdown("##### Dettagli Articolo Trovato")
            c_d1, c_d2, c_d3, c_d4 = st.columns(4)
            c_d1.metric("SKU 13", item["sku13"])
            c_d2.metric("SKU 7", item["sku7"])
            c_d3.metric("Marchio", item["brand"] or "-")
            stag_attuale = item.get("stagione_completa") or (
                f"{item['stagione']}/{item['semestre']}" if item.get('semestre') else (item.get('stagione') or "-")
            )
            c_d4.metric("Stagione Attuale", stag_attuale)

            c_info1, c_info2 = st.columns([2, 1])
            with c_info1:
                st.markdown(f"**Descrizione:** {item['descrizione'] or '-'}")
                st.markdown(f"**Linea / Serie:** {item['linea'] or '-'} &nbsp;|&nbsp; **Genere:** {item['genere'] or '-'}")
            with c_info2:
                st.markdown(f"**Categoria:** {item['categoria'] or '-'} &nbsp;|&nbsp; **Tg Base:** {item['taglia_base'] or '-'}")
                st.caption(f"Ultimo aggiornamento: {item['aggiornato_il']}")

            st.write("")
            section("Modifica la Stagione", caption="Specifica il nuovo valore della stagione (formato anno/stagione, es. 2026/1 o 2026/2) da salvare nel DB.")

            # Suggerimenti di stagioni frequenti o input manuale
            stag_expr = "CASE WHEN semestre IS NOT NULL AND semestre != '' THEN stagione || '/' || semestre ELSE stagione END"
            stagioni_frequenti = [r[0] for r in conn.execute(
                f"SELECT {stag_expr} AS stag_full FROM anagrafica WHERE stagione IS NOT NULL AND stagione != '' GROUP BY stag_full ORDER BY COUNT(*) DESC LIMIT 8"
            ).fetchall() if r[0]]

            c_edit1, c_edit2 = st.columns([1.5, 2])
            with c_edit1:
                nuova_stagione_input = st.text_input(
                    "Nuova Stagione (Anno/Stagione)",
                    value=stag_attuale if stag_attuale != "-" else "",
                    placeholder="es. 2026/1, 2026/2, 2025/2...",
                    key="txt_new_stagione"
                )
            with c_edit2:
                if stagioni_frequenti:
                    st.caption("Oppure scegli una stagione frequente:")
                    s_btns = st.columns(len(stagioni_frequenti[:5]))
                    for i, sf in enumerate(stagioni_frequenti[:5]):
                        if s_btns[i].button(sf, key=f"btn_sf_{sf}"):
                            st.session_state["txt_new_stagione"] = sf
                            st.rerun()

            aggiorna_tutte_le_varianti = st.checkbox(
                f"Aggiorna la stagione per TUTTE le varianti dello stesso modello SKU7 (**{item['sku7']}**)",
                value=False,
                key="chk_aggiorna_tutto_sku7"
            )

            if st.button("💾 Salva Nuova Stagione", type="primary", key="btn_salva_nuova_stag"):
                if not nuova_stagione_input.strip():
                    st.error("Inserisci un valore valido per la stagione.")
                else:
                    n_up = db.aggiorna_stagione_anagrafica(
                        conn,
                        sku=item["sku13"],
                        nuova_stagione=nuova_stagione_input,
                        aggiorna_sku7=aggiorna_tutte_le_varianti
                    )
                    st.session_state.pop("anagrafica", None)
                    st.session_state["rigenera_pipeline"] = True
                    st.success(f"✅ Stagione aggiornata a **'{nuova_stagione_input.strip()}'** per **{n_up}** record nel DB!")
                    st.rerun()


# =======================================================================================
# TAB 5: IMPORT & MANUTENZIONE DB
# =======================================================================================
with tab_import:
    section("Caricamento File Anagrafica nel Database",
            caption="Carica nuovi file anagrafica (es. anagrafica_261.csv, anagrafica_262.csv). "
                    "Gli articoli già esistenti vengono aggiornati con i dati più recenti.")

    anagrafica_files = st.file_uploader(
        "Uno o più file ANAGRAFICA (TSV/CSV)", type=["csv", "tsv", "txt"],
        accept_multiple_files=True, key="anag_page_files"
    )

    c_btn1, c_btn2 = st.columns([1.5, 1.5])
    with c_btn1:
        carica_anag = st.button("Salva ANAGRAFICA nel DB", disabled=not anagrafica_files, type="primary", width="stretch", key="btn_save_anag_page")
    with c_btn2:
        with st.popover("🗑️ Elimina solo Anagrafica", disabled=tot_sku13 == 0, width="stretch"):
            st.warning("Stai per cancellare l'intera tabella anagrafica dal DB.")
            st.caption("I dati delle vendite e dei resi NON verranno toccati.")
            if st.button("Conferma eliminazione anagrafica", type="primary", width="stretch", key="btn_conf_del_anag_page"):
                db.svuota_anagrafica(conn)
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

        # Pulizia cache sessione
        st.session_state.pop("anagrafica", None)
        st.session_state["rigenera_pipeline"] = True

        # Sincronizzazione automatica genere
        with st.spinner("Sincronizzazione automatica del genere sulle vendite…"):
            n_up_gen = db.sincronizza_genere_righe(conn)
            st.info(f"🔄 Genere sincronizzato su **{n_up_gen:,}** righe di vendita/reso.".replace(",", "."))
        st.rerun()

    st.divider()
    section("Cronologia Caricamenti Anagrafica")
    try:
        df_log_anag = pd.read_sql_query(
            "SELECT ts, fonte_file, righe_nel_file, righe_nuove, righe_gia_presenti "
            "FROM upload_log WHERE tipo = 'ANAGRAFICA' ORDER BY ts DESC LIMIT 10",
            conn
        )
        if not df_log_anag.empty:
            df_log_anag.rename(columns={
                "ts": "Data/Ora",
                "fonte_file": "File / Operazione",
                "righe_nel_file": "Righe nel File",
                "righe_nuove": "Nuove Inserite",
                "righe_gia_presenti": "Aggiornate/Sostituite"
            }, inplace=True)
            data_table(df_log_anag, key="dt_log_anag")
        else:
            st.caption("Nessuna voce di log registrata.")
    except Exception:
        pass
