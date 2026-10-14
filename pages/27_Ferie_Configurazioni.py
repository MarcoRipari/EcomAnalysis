from datetime import datetime
import pandas as pd
import streamlit as st

from core import db, ferie, roles
from core.design_system import page_setup

page_setup("Configurazioni", None)

conn = db.connect()
ferie.init_ferie_tables(conn)

user_email = st.session_state.get("user_email")
if not user_email:
    sess = st.session_state.get("auth", {}).get("user", {}) or {}
    user_email = sess.get("email", "")

user_role = st.session_state.get("user_role")
if not user_role:
    user_role = roles.get_user_role(conn, user_email)

is_admin = (user_role == "Admin")

if not is_admin:
    st.error("Accesso Negato: questa sezione è riservata esclusivamente agli amministratori.")
    st.stop()

df_dipendenti = ferie.get_dipendenti(conn, solo_attivi=True)
df_storico = ferie.get_ferie_storico(conn)
anno_corrente = datetime.now().year


# ------------------------------------------------------------------ Tab 1: Saldi & Disponibilità
def _render_tab_saldi():
    st.caption(f"Saldi calcolati per l'esercizio {anno_corrente} comprensivi di riporto dagli esercizi precedenti.")

    if df_dipendenti.empty:
        st.info("Nessun dipendente registrato. Configura i dipendenti nel tab 'Gestione Dipendenti'.")
        return

    cols = st.columns(3)
    righe_riepilogo = []

    for i, dip in enumerate(df_dipendenti.itertuples(index=False)):
        riepilogo = ferie.calcola_riepilogo_ferie_annuale(df_storico, dip.nome, dip.totale_annuo)
        dati = riepilogo[anno_corrente]
        usati = dati["usati"]
        disponibili = dati["disponibili"]
        residuo = dati["residuo"]

        percentuale = min(usati / disponibili, 1.0) if disponibili > 0 else 1.0
        percentuale = max(percentuale, 0.0)

        colore_residuo = "#DC2626" if residuo < 5 else "#0D9488"
        colore_barra = "#DC2626" if residuo < 0 else "#0D9488"

        righe_riepilogo.append({
            "Dipendente": dip.nome,
            "Budget Annuo": f"{dip.totale_annuo:g} gg",
            "Disponibili (con riporto)": ferie.formatta_giorni_ore(disponibili),
            "Godute": ferie.formatta_giorni_ore(usati),
            "Residuo Attuale": ferie.formatta_giorni_ore(residuo),
            "_residuo_num": residuo,
        })

        with cols[i % 3]:
            st.markdown(f"""
            <div style="border:1px solid #E2E8F0; padding:16px; border-radius:8px; background:#FFFFFF; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
                <div style="font-weight:700; color:#0F172A; font-size:16px; margin-bottom:4px;">{dip.nome}</div>
                <div style="font-size:13px; color:#64748B; margin-bottom:4px;">
                    Godute: <b>{ferie.formatta_giorni_ore(usati)}</b> / {ferie.formatta_giorni_ore(disponibili)}
                </div>
                <div style="font-size:15px; color:{colore_residuo}; font-weight:700; margin-bottom:8px;">
                    Residuo: {ferie.formatta_giorni_ore(residuo)}
                </div>
                <div style="background:#F1F5F9; border-radius:4px; height:8px; width:100%; overflow:hidden;">
                    <div style="background:{colore_barra}; height:100%; width:{percentuale*100}%; border-radius:4px;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    if righe_riepilogo:
        st.markdown("#### Riepilogo Generale Saldi")
        df_tab = pd.DataFrame(righe_riepilogo).drop(columns=["_residuo_num"])
        st.dataframe(df_tab, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ Tab 2: Gestione Dipendenti
def _render_tab_dipendenti():
    st.markdown("#### Dipendenti Attivi")
    if df_dipendenti.empty:
        st.info("Nessun dipendente censito nel database.")
    else:
        for _, dip_row in df_dipendenti.iterrows():
            with st.expander(f"{dip_row['nome']} — {dip_row['totale_annuo']:g} gg annui", expanded=False):
                with st.form(f"form_mod_dip_{dip_row['id']}"):
                    c_n, c_e, c_b = st.columns(3)
                    with c_n:
                        mod_nome = st.text_input("Nome e Cognome", value=dip_row["nome"])
                    with c_e:
                        mod_email = st.text_input("Email", value=dip_row.get("email", "") or "")
                    with c_b:
                        mod_budget = st.number_input("Budget Annuo (gg)", value=float(dip_row["totale_annuo"]), min_value=0.0, step=0.5)

                    st.markdown("**Orario Contrattuale di Riferimento**")
                    o1, o2, o3, o4 = st.columns(4)
                    with o1:
                        mat_in = st.text_input("Mattina Inizio (HH:MM)", value=dip_row["mattina_inizio"])
                    with o2:
                        mat_out = st.text_input("Mattina Fine (HH:MM)", value=dip_row["mattina_fine"])
                    with o3:
                        pom_in = st.text_input("Pomeriggio Inizio (HH:MM)", value=dip_row["pomeriggio_inizio"])
                    with o4:
                        pom_out = st.text_input("Pomeriggio Fine (HH:MM)", value=dip_row["pomeriggio_fine"])

                    c_b_mod, c_b_del = st.columns([1, 1])
                    with c_b_mod:
                        sub_mod = st.form_submit_button("Aggiorna Dipendente", type="primary", use_container_width=True)
                    with c_b_del:
                        sub_del = st.form_submit_button("Disattiva Dipendente", use_container_width=True)

                    if sub_mod:
                        ok_up, msg_up = ferie.update_dipendente(
                            conn, dip_row["nome"], mod_nome, mod_email, mod_budget,
                            {
                                "mattina_inizio": mat_in,
                                "mattina_fine": mat_out,
                                "pomeriggio_inizio": pom_in,
                                "pomeriggio_fine": pom_out,
                            }
                        )
                        if ok_up:
                            st.success(msg_up)
                            st.rerun()
                        else:
                            st.error(msg_up)

                    if sub_del:
                        ok_del, msg_del = ferie.delete_dipendente(conn, dip_row["nome"])
                        if ok_del:
                            st.success(msg_del)
                            st.rerun()
                        else:
                            st.error(msg_del)

    st.divider()

    budget_default_attuale = ferie.get_budget_annuo_default(conn)
    st.markdown("#### Aggiungi Nuovo Dipendente")
    with st.form("form_nuovo_dipendente"):
        c_new1, c_new2, c_new3 = st.columns(3)
        with c_new1:
            new_nome = st.text_input("Nome e Cognome *")
        with c_new2:
            new_email = st.text_input("Email (facoltativa)")
        with c_new3:
            new_budget = st.number_input("Budget Annuo Giorni", value=float(budget_default_attuale), min_value=0.0, step=0.5)

        st.markdown("**Orario Contrattuale**")
        o_n1, o_n2, o_n3, o_n4 = st.columns(4)
        with o_n1:
            n_mat_in = st.text_input("Mattina Inizio", value="08:00")
        with o_n2:
            n_mat_out = st.text_input("Mattina Fine", value="12:00")
        with o_n3:
            n_pom_in = st.text_input("Pomeriggio Inizio", value="14:00")
        with o_n4:
            n_pom_out = st.text_input("Pomeriggio Fine", value="18:00")

        salva_nuovo = st.form_submit_button("Crea Dipendente", type="primary")
        if salva_nuovo:
            ok_add, msg_add = ferie.add_dipendente(
                conn, new_nome, email=new_email, totale_annuo=new_budget,
                mattina_inizio=n_mat_in, mattina_fine=n_mat_out,
                pomeriggio_inizio=n_pom_in, pomeriggio_fine=n_pom_out,
            )
            if ok_add:
                st.success(msg_add)
                st.rerun()
            else:
                st.error(msg_add)

    st.write("")
    if st.button("🔄 Sincronizza da Utenti di Sistema", help="Importa automaticamente utenti configurati che non sono ancora in anagrafica dipendenti"):
        n_agg = ferie.sync_utenti_con_dipendenti(conn)
        if n_agg > 0:
            st.success(f"Aggiunti {n_agg} nuovi dipendenti!")
            st.rerun()
        else:
            st.info("Tutti gli utenti di sistema risultano già censiti.")


# ------------------------------------------------------------------ Tab 3: Dettaglio Storico
def _render_tab_storico():
    if df_dipendenti.empty:
        st.info("Nessun dipendente registrato.")
        return

    nomi_disp = df_dipendenti["nome"].tolist()
    c_sel, _ = st.columns([2, 1])
    with c_sel:
        dip_scelto = st.selectbox("Seleziona Dipendente", options=nomi_disp, key="cfg_storico_dip_scelto")

    dip_info = df_dipendenti[df_dipendenti["nome"] == dip_scelto].iloc[0]
    storico_dip = df_storico[df_storico["nome"] == dip_scelto].copy() if not df_storico.empty else pd.DataFrame()

    f1, f2 = st.columns(2)
    with f1:
        anni_disp = ["Tutti"]
        if not storico_dip.empty:
            anni_estratti = sorted(pd.to_datetime(storico_dip["data_inizio"]).dt.year.dropna().unique().astype(int).tolist(), reverse=True)
            anni_disp.extend([str(a) for a in anni_estratti])
        anno_filtro = st.selectbox("Filtra per Anno", options=anni_disp, key="cfg_storico_filtro_anno")

    with f2:
        tipi_disp = ["Tutti"]
        if not storico_dip.empty:
            tipi_disp.extend(sorted(storico_dip["tipo"].dropna().unique().tolist()))
        tipo_filtro = st.selectbox("Filtra per Tipologia", options=tipi_disp, key="cfg_storico_filtro_tipo")

    filtrato = storico_dip.copy()
    if not filtrato.empty:
        if anno_filtro != "Tutti":
            filtrato = filtrato[pd.to_datetime(filtrato["data_inizio"]).dt.year == int(anno_filtro)]
        if tipo_filtro != "Tutti":
            filtrato = filtrato[filtrato["tipo"] == tipo_filtro]

        filtrato["DATA INIZIO"] = pd.to_datetime(filtrato["data_inizio"]).dt.date
        filtrato["DATA FINE"] = pd.to_datetime(filtrato["data_fine"]).dt.date
        filtrato["TIPO"] = filtrato["tipo"]
        filtrato["GIORNI LAVORATIVI"] = filtrato["giorni_lavorativi"]
        filtrato["DETTAGLIO"] = filtrato["dettaglio"]
        filtrato["NOTE"] = filtrato["note"]

    colonne_mostrate = ["DATA INIZIO", "DATA FINE", "TIPO", "GIORNI LAVORATIVI", "DETTAGLIO", "NOTE"]
    df_editor_input = filtrato[colonne_mostrate].copy() if not filtrato.empty else pd.DataFrame(columns=colonne_mostrate)

    st.markdown(f"##### Modifica Assenze: {dip_scelto}")
    edited = st.data_editor(
        df_editor_input,
        column_config={
            "DATA INIZIO": st.column_config.DateColumn("Inizio", format="DD/MM/YYYY", required=True),
            "DATA FINE": st.column_config.DateColumn("Fine", format="DD/MM/YYYY", required=True),
            "TIPO": st.column_config.SelectboxColumn("Tipologia", options=["Ferie", "Permesso Orario", "Rettifica", "Altro"], required=True),
            "GIORNI LAVORATIVI": st.column_config.NumberColumn("Giorni", format="%.2f"),
            "DETTAGLIO": st.column_config.TextColumn("Dettaglio Permesso"),
            "NOTE": st.column_config.TextColumn("Note"),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"editor_cfg_storico_{dip_scelto}",
    )

    c_save, c_export = st.columns(2)
    with c_save:
        if st.button("Salva modifiche storiche", use_container_width=True, type="primary"):
            if anno_filtro != "Tutti" or tipo_filtro != "Tutti":
                mask = (pd.to_datetime(storico_dip["data_inizio"]).dt.year == int(anno_filtro)) if anno_filtro != "Tutti" else True
                if tipo_filtro != "Tutti":
                    mask &= (storico_dip["tipo"] == tipo_filtro)
                df_escluse = storico_dip[~mask].copy()
                df_escluse["DATA INIZIO"] = pd.to_datetime(df_escluse["data_inizio"]).dt.date
                df_escluse["DATA FINE"] = pd.to_datetime(df_escluse["data_fine"]).dt.date
                df_escluse["TIPO"] = df_escluse["tipo"]
                df_escluse["GIORNI LAVORATIVI"] = df_escluse["giorni_lavorativi"]
                df_escluse["DETTAGLIO"] = df_escluse["dettaglio"]
                df_escluse["NOTE"] = df_escluse["note"]
                df_finale = pd.concat([df_escluse[colonne_mostrate], edited], ignore_index=True)
            else:
                df_finale = edited

            ok, msg = ferie.sync_ferie_changes(conn, dip_scelto, df_finale)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with c_export:
        if not edited.empty:
            csv_bytes = edited.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Esporta report (CSV)",
                data=csv_bytes,
                file_name=f"ferie_{dip_scelto}_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    riepilogo_storico = ferie.calcola_riepilogo_ferie_annuale(df_storico, dip_scelto, dip_info["totale_annuo"])
    dati_corrente = riepilogo_storico[anno_corrente]

    colore_card = "#DC2626" if dati_corrente["residuo"] < 5 else "#0D9488"
    st.markdown(f"""
    <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid {colore_card}; padding:14px; border-radius:6px; margin-top:20px;">
        <div style="font-weight:700; font-size:15px; color:#0F172A; margin-bottom:8px;">
            Riepilogo {dip_scelto} — Esercizio {anno_corrente}
        </div>
        <div style="display:flex; justify-content:space-between; font-size:13px; color:#475569; padding:3px 0;">
            <span>Disponibilità Totale (Budget + Riporto Pregresso):</span>
            <b>{ferie.formatta_giorni_ore(dati_corrente['disponibili'])}</b>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:13px; color:#475569; padding:3px 0;">
            <span>Giorni Fruiti:</span>
            <b>{ferie.formatta_giorni_ore(dati_corrente['usati'])}</b>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:14px; color:{colore_card}; border-top:1px solid #E2E8F0; padding-top:6px; margin-top:4px;">
            <b>Residuo Attuale:</b>
            <b style="font-size:16px;">{ferie.formatta_giorni_ore(dati_corrente['residuo'])}</b>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ------------------------------------------------------------------ Tab 4: Impostazioni
def _render_tab_impostazioni():
    st.markdown("#### Configurazione Parametri Ferie")

    budget_corrente = ferie.get_budget_annuo_default(conn)

    with st.container(border=True):
        st.markdown("##### Budget Annuo Predefinito")
        st.caption(
            "Specifica il numero di giorni di ferie annui predefiniti assegnati ai nuovi dipendenti "
            "e a tutti gli utenti sincronizzati nel sistema."
        )

        c1, c2 = st.columns([2, 1])
        with c1:
            nuovo_budget = st.number_input(
                "Budget Annuo Default (giorni)",
                value=float(budget_corrente),
                min_value=1.0,
                max_value=365.0,
                step=0.5,
                key="input_budget_default",
            )
        with c2:
            st.write("")
            st.write("")
            if st.button("Salva Configurazione", type="primary", use_container_width=True):
                if ferie.set_budget_annuo_default(conn, nuovo_budget):
                    st.success(f"Budget annuo predefinito aggiornato a **{nuovo_budget:g} giorni**!")
                    st.rerun()
                else:
                    st.error("Errore durante il salvataggio della configurazione.")

        st.divider()

        st.markdown("##### Allineamento Dipendenti Esistenti")
        st.caption(
            "Puoi applicare questo valore a tutti i dipendenti attualmente attivi nel sistema "
            "aggiornando in blocco il loro monte ferie contrattuale."
        )

        if st.button(f"Applica {nuovo_budget:g} giorni a tutti i dipendenti attivi", use_container_width=False):
            ok_all, n_mod = ferie.applica_budget_a_tutti_i_dipendenti(conn, nuovo_budget)
            if ok_all:
                st.success(f"Aggiornati con successo **{n_mod} dipendenti** al budget di {nuovo_budget:g} giorni!")
                st.rerun()
            else:
                st.error("Errore durante l'aggiornamento dei dipendenti.")


# ------------------------------------------------------------------ Rendering a 4 Tab
tab_saldi, tab_dipendenti, tab_storico, tab_impostazioni = st.tabs([
    "Saldi & Disponibilità",
    "Gestione Dipendenti",
    "Dettaglio Storico",
    "Impostazioni",
])

with tab_saldi:
    _render_tab_saldi()

with tab_dipendenti:
    _render_tab_dipendenti()

with tab_storico:
    _render_tab_storico()

with tab_impostazioni:
    _render_tab_impostazioni()
