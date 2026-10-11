import dataclasses
import json

import pandas as pd
import streamlit as st

from core import correzioni as cz
from core import db
from core.design_system import page_setup, section, data_table, empty_state
from core.ui_helpers import number_col

page_setup("Correzioni DB", "🛠️",
           "Trova e sostituisci nel DB: scegli la colonna, cosa cercare, con cosa sostituire e le condizioni")

conn = db.connect()
if conn.execute("SELECT 1 FROM righe LIMIT 1").fetchone() is None:
    empty_state("Il DB è vuoto: non c'è niente da correggere.")
    st.stop()

st.warning("Le correzioni modificano il DB in modo permanente. Controlla sempre l'anteprima; "
           "conviene tenere una copia di `data/ecombi.db` prima di correzioni grandi.")

ETICHETTA_COL = cz.COLONNE_MODIFICABILI
ETICHETTA_COND = cz.COLONNE_CONDIZIONE
inverso_cond = {v: k for k, v in ETICHETTA_COND.items()}

# ------------------------------------------------------------------------------- 1. regola
section("1. Cosa correggere")
c1, c2, c3 = st.columns([2, 2, 3])
colonna = c1.selectbox("Colonna da modificare", list(ETICHETTA_COL), format_func=ETICHETTA_COL.get)
operatore = c2.selectbox("Cerca le righe in cui il valore…", cz.OPERATORI)
senza_valore = operatore in ("è vuoto", "non è vuoto")
cerca = c3.text_input("Testo da cercare", disabled=senza_valore, placeholder="es. UNITED KIN")
c4, c5, c6 = st.columns([3, 3, 2])
sostituisci = c4.text_input("Sostituisci con", placeholder="es. GB")
modo = c5.radio("Come sostituire", list(cz.MODI), format_func=cz.MODI.get, horizontal=True,
                help="«Intero valore»: la cella diventa esattamente il testo indicato. «Solo il testo trovato»: "
                     "cambia soltanto la parte cercata (es. cerco «KINGDOM», sostituisco con «KD»).")
ignora = c6.checkbox("Ignora maiuscole/minuscole", value=True)

# ------------------------------------------------------------------------------- 2. condizioni
section("2. Condizioni (facoltative)",
        caption="La correzione si applica solo alle righe che rispettano TUTTE le condizioni indicate qui sotto.")
condizioni_df = st.data_editor(
    pd.DataFrame({"Colonna": pd.Series(dtype="str"), "Operatore": pd.Series(dtype="str"),
                  "Valore": pd.Series(dtype="str")}),
    num_rows="dynamic", width="stretch", key="corr_condizioni",
    column_config={
        "Colonna": st.column_config.SelectboxColumn(options=list(ETICHETTA_COND.values()), required=True),
        "Operatore": st.column_config.SelectboxColumn(options=cz.OPERATORI, required=True, default="uguale a"),
        "Valore": st.column_config.TextColumn(),
    })
usa_date = st.checkbox("Limita per Data Pagamento (data vendita)")
data_da = data_a = None
if usa_date:
    d1, d2 = st.columns(2)
    data_da = d1.date_input("Dal", format="DD/MM/YYYY", key="corr_da").isoformat()
    data_a = d2.date_input("Al", format="DD/MM/YYYY", key="corr_a").isoformat()

condizioni = [{"colonna": inverso_cond[r["Colonna"]], "operatore": r["Operatore"], "valore": r["Valore"] or ""}
              for _, r in condizioni_df.dropna(subset=["Colonna", "Operatore"]).iterrows()]
regola = cz.Regola(colonna=colonna, operatore=operatore, cerca="" if senza_valore else cerca,
                   sostituisci=sostituisci, modo=modo, ignora_maiuscole=ignora, condizioni=condizioni,
                   data_da=data_da, data_a=data_a)
firma = json.dumps(dataclasses.asdict(regola), sort_keys=True)

# ------------------------------------------------------------------------------- 3. anteprima
section("3. Anteprima e applicazione")
if st.button("🔍 Anteprima", type="primary"):
    try:
        st.session_state["corr_anteprima"] = (firma, cz.anteprima(conn, regola))
    except ValueError as e:
        st.session_state.pop("corr_anteprima", None)
        st.error(str(e))

anteprima = st.session_state.get("corr_anteprima")
if anteprima:
    firma_anteprima, ris = anteprima
    if firma_anteprima != firma:
        st.info("I parametri sono cambiati dopo l'ultima anteprima: rilanciala prima di applicare.")
    elif ris["totale"] == 0:
        empty_state("Nessuna riga verrebbe modificata con questi parametri.", "🔍")
    else:
        st.success(f"**{ris['totale']:,}** righe verrebbero modificate.".replace(",", "."))
        data_table(ris["mappa"], {"Righe": number_col()})
        with st.expander("Esempi di righe interessate"):
            data_table(ris["campione"])

        salva = st.checkbox(
            "Salva anche come regola: applicala automaticamente ai prossimi file caricati",
            disabled=not regola.salvabile,
            help="Evita che il valore errato rientri dai nuovi DATASET/RESI." if regola.salvabile else
                 "Le condizioni su «Stato riga» e «File di origine» non si possono salvare come regola.")
        conferma = st.checkbox("Ho controllato l'anteprima e voglio modificare il DB")
        if st.button("✅ Applica correzione", disabled=not conferma):
            try:
                n = cz.applica(conn, regola)
                if salva:
                    cz.salva_regola(conn, regola)
                st.session_state.pop("corr_anteprima", None)
                st.session_state["rigenera_pipeline"] = True      # i report si ricalcolano con i dati corretti
                st.success(f"Correzione applicata: {n:,} righe modificate.".replace(",", ".")
                           + (" Regola salvata per i prossimi caricamenti." if salva else ""))
            except Exception as e:  # noqa: BLE001
                st.error(f"Correzione non applicata (nessuna modifica salvata): {e}")

# ------------------------------------------------------------------------------- regole e storico
section("Regole salvate", caption="Applicate automaticamente a ogni DATASET e RESI caricato.")
regole = cz.elenco_regole(conn)
if regole.empty:
    st.caption("Nessuna regola salvata.")
else:
    data_table(regole)
    da_eliminare = st.selectbox("Elimina la regola", [None] + list(regole["ID"]),
                                format_func=lambda x: "—" if x is None else f"Regola {x}")
    if da_eliminare is not None and st.button("🗑️ Elimina regola"):
        cz.elimina_regola(conn, da_eliminare)
        st.rerun()

section("Storico correzioni")
storico = cz.elenco_log(conn)
if storico.empty:
    st.caption("Nessuna correzione eseguita.")
else:
    data_table(storico, {"Righe": number_col()})
