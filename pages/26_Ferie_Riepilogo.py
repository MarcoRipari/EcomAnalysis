from datetime import date, datetime
import pandas as pd
import streamlit as st

from core import db, ferie, roles
from core.design_system import page_setup

page_setup("Riepilogo", None)

conn = db.connect()
ferie.init_ferie_tables(conn)

df_dipendenti = ferie.get_dipendenti(conn, solo_attivi=True)
df_storico = ferie.get_ferie_storico(conn)
anno_corrente = datetime.now().year

user_email = st.session_state.get("user_email")
if not user_email:
    sess = st.session_state.get("auth", {}).get("user", {}) or {}
    user_email = sess.get("email", "")

user_role = st.session_state.get("user_role")
if not user_role:
    user_role = roles.get_user_role(conn, user_email)

is_admin = (user_role == "Admin")


# ------------------------------------------------------------------ Componente Scheda Personale Dettagliata
def render_dettaglio_dipendente(info_pers: pd.Series | dict, df_storico: pd.DataFrame, anno_corrente: int):
    """Renderizza la scheda del saldo ferie e lo storico assenze per un singolo dipendente."""
    dip_nome = info_pers["nome"]
    totale_annuo = float(info_pers["totale_annuo"])
    riepilogo_pers = ferie.calcola_riepilogo_ferie_annuale(df_storico, dip_nome, totale_annuo)
    dati_p = riepilogo_pers[anno_corrente]

    colore_res = "#DC2626" if dati_p["residuo"] < 5 else "#0D9488"
    colore_bar = "#DC2626" if dati_p["residuo"] < 0 else "#0D9488"
    pct = min(dati_p["usati"] / dati_p["disponibili"], 1.0) if dati_p["disponibili"] > 0 else 1.0
    pct = max(pct, 0.0)

    # Indicatori Saldo Annuale (KPI)
    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(f"""
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; padding:14px 16px; border-radius:8px;">
            <div style="font-size:12px; color:#64748B; font-weight:600; text-transform:uppercase;">Disponibili ({anno_corrente})</div>
            <div style="font-size:22px; font-weight:700; color:#0F172A; margin-top:4px;">{ferie.formatta_giorni_ore(dati_p['disponibili'])}</div>
            <div style="font-size:11px; color:#94A3B8; margin-top:2px;">Budget annuo: {totale_annuo:g} gg + riporto</div>
        </div>
        """, unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; padding:14px 16px; border-radius:8px;">
            <div style="font-size:12px; color:#64748B; font-weight:600; text-transform:uppercase;">Godute / Fruite</div>
            <div style="font-size:22px; font-weight:700; color:#0F172A; margin-top:4px;">{ferie.formatta_giorni_ore(dati_p['usati'])}</div>
            <div style="font-size:11px; color:#94A3B8; margin-top:2px;">Ferie e permessi orari goduti</div>
        </div>
        """, unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-left:4px solid {colore_res}; padding:14px 16px; border-radius:8px;">
            <div style="font-size:12px; color:#64748B; font-weight:600; text-transform:uppercase;">Residuo Attuale</div>
            <div style="font-size:22px; font-weight:700; color:{colore_res}; margin-top:4px;">{ferie.formatta_giorni_ore(dati_p['residuo'])}</div>
            <div style="font-size:11px; color:#94A3B8; margin-top:2px;">Saldo netto aggiornato</div>
        </div>
        """, unsafe_allow_html=True)

    # Barra di avanzamento
    st.markdown(f"""
    <div style="margin-top:12px; margin-bottom:24px;">
        <div style="display:flex; justify-content:space-between; font-size:12px; color:#64748B; margin-bottom:4px;">
            <span>Avanzamento fruizione ({pct*100:.1f}%)</span>
            <span>Residuo: {ferie.formatta_giorni_ore(dati_p['residuo'])}</span>
        </div>
        <div style="background:#F1F5F9; border-radius:4px; height:8px; width:100%; overflow:hidden;">
            <div style="background:{colore_bar}; height:100%; width:{pct*100}%; border-radius:4px;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    oggi_dt = datetime.now().date()
    mio_storico = df_storico[df_storico["nome"] == dip_nome].copy() if not df_storico.empty else pd.DataFrame()

    if not mio_storico.empty:
        mio_storico["_inizio"] = pd.to_datetime(mio_storico["data_inizio"]).dt.date
        mio_storico["_fine"] = pd.to_datetime(mio_storico["data_fine"]).dt.date

        future = mio_storico[mio_storico["_fine"] >= oggi_dt].sort_values(by="_inizio")
        st.markdown("##### Prossime Assenze Programmate")
        if future.empty:
            st.caption("Nessuna assenza programmata per i prossimi mesi.")
        else:
            for _, r in future.iterrows():
                d_in = r["_inizio"]
                d_fi = r["_fine"]
                icona_tipo = "🕐 " if r.get("tipo") == "Permesso Orario" else ""
                if d_in == d_fi:
                    label_p = f"{icona_tipo}{ferie.formatta_data_lunga(d_in)} ({r['tipo']})"
                else:
                    label_p = f"{icona_tipo}Dal {ferie.formatta_data_lunga(d_in)} al {ferie.formatta_data_lunga(d_fi)} ({r['tipo']})"
                if r.get("dettaglio"):
                    label_p += f" — {r['dettaglio']}"
                if r.get("note"):
                    label_p += f" *(Note: {r['note']})*"
                st.markdown(f"- {label_p}")

        passate = mio_storico[mio_storico["_fine"] < oggi_dt].sort_values(by="_inizio", ascending=False)
        st.markdown("##### Storico Assenze Fruite")
        if passate.empty:
            st.caption("Nessuna assenza passata registrata.")
        else:
            passate_mostra = passate[["data_inizio", "data_fine", "tipo", "giorni_lavorativi", "dettaglio", "note"]].rename(columns={
                "data_inizio": "Inizio",
                "data_fine": "Fine",
                "tipo": "Tipo",
                "giorni_lavorativi": "Giorni",
                "dettaglio": "Dettaglio",
                "note": "Note",
            })
            st.dataframe(passate_mostra, use_container_width=True, hide_index=True)

    anni_passati = sorted([a for a in riepilogo_pers if a < anno_corrente], reverse=True)
    if anni_passati:
        with st.expander("Esercizi Precedenti"):
            for a_prec in anni_passati:
                d_p = riepilogo_pers[a_prec]
                c_p = "#DC2626" if d_p["residuo"] < 0 else "#475569"
                st.markdown(
                    f"**{a_prec}**: Godute {ferie.formatta_giorni_ore(d_p['usati'])} &nbsp;|&nbsp; "
                    f"Residuo a chiusura: <span style='color:{c_p}; font-weight:700;'>{ferie.formatta_giorni_ore(d_p['residuo'])}</span>",
                    unsafe_allow_html=True,
                )


# ------------------------------------------------------------------ Render Pagina Riepilogo
if df_dipendenti.empty:
    st.info("Nessun dipendente registrato. Configura i dipendenti nella sezione Configurazioni Ferie.")
    st.stop()

if is_admin:
    # Admin: visualizza tutte le schede con selettore in cima
    nomi_disp = df_dipendenti["nome"].tolist()
    
    idx_default = 0
    email_clean = (user_email or "").strip().lower()
    if email_clean:
        corrisp = df_dipendenti[df_dipendenti["email"].str.lower() == email_clean]
        if not corrisp.empty and corrisp.iloc[0]["nome"] in nomi_disp:
            idx_default = nomi_disp.index(corrisp.iloc[0]["nome"])

    c_sel, _ = st.columns([2, 1])
    with c_sel:
        dip_selezionato = st.selectbox(
            "Seleziona Scheda Dipendente",
            options=nomi_disp,
            index=idx_default,
            key="riepilogo_admin_sel"
        )

    info_dip = df_dipendenti[df_dipendenti["nome"] == dip_selezionato].iloc[0]
    render_dettaglio_dipendente(info_dip, df_storico, anno_corrente)

else:
    # Utente Standard: visualizzazione riservata esclusivamente alla propria scheda personale
    email_clean = (user_email or "").strip().lower()
    dip_match = pd.DataFrame()
    if email_clean:
        dip_match = df_dipendenti[df_dipendenti["email"].str.lower() == email_clean]
    if dip_match.empty and email_clean:
        nome_presunto = ferie.nome_da_email(email_clean)
        dip_match = df_dipendenti[df_dipendenti["nome"].str.lower() == nome_presunto.lower()]

    if dip_match.empty:
        st.info(
            f"Nessuna posizione dipendente attiva associata alla tua utenza ({user_email}). "
            "Contatta un amministratore per configurare la tua anagrafica."
        )
    else:
        info_pers = dip_match.iloc[0]
        st.markdown(f"### {info_pers['nome']}")
        st.caption(f"Posizione: Dipendente · Email: {info_pers.get('email', '')} · Budget contrattuale annuo: {float(info_pers['totale_annuo']):g} gg")
        render_dettaglio_dipendente(info_pers, df_storico, anno_corrente)
