"""Modulo Site Knowledge & Navigation Graph per EcomAnalysis.

Fornisce all'LLM e al sistema la mappa completa delle funzionalità, pagine,
controlli operativi (Topbar, filtri), metriche e guide passo-passo dell'applicazione.
Compatibile con l'estrazione architetturale AST di Graphify.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Mappa Strutturata delle Pagine e Funzionalità del Portale
# ---------------------------------------------------------------------------
SITE_SECTIONS: dict[str, dict[str, Any]] = {
    "Analisi Dati": {
        "descrizione": "Cruscotti analitici e reportistica sulle vendite e sui resi e-commerce.",
        "controlli_globali": "Topbar in alto (Perimetro, Periodo di Analisi con date range, Confronto Y-2, pulsante Applica).",
        "pagine": {
            "01_Dashboard": {
                "titolo": "Dashboard",
                "percorso": "Analisi Dati > Dashboard",
                "scopo": "Panoramica direzionale delle vendite: KPI principali (Fatturato Netto, Paia Spedite, % Reso, Sconto Medio), andamento temporale giornaliero/settimanale e confronto con l'anno precedente.",
                "quando_usarla": "Per una vista d'insieme immediata su fatturato e volumi di un periodo specifico.",
            },
            "02_Y2Y_Generale": {
                "titolo": "Y2Y Generale",
                "percorso": "Analisi Dati > Y2Y Generale",
                "scopo": "Confronto analitico tra il periodo selezionato e lo stesso periodo dell'anno precedente (o triennale con Y-2), con delta % su fatturato, paia e prezzi medi.",
                "quando_usarla": "Per capire la crescita o contrazione rispetto all'anno scorso.",
            },
            "03_Articoli_e_Collezioni": {
                "titolo": "Articoli & Collezioni",
                "percorso": "Analisi Dati > Articoli & Collezioni",
                "scopo": "Analisi delle vendite segmentate per Linea di prodotto, Collezione, Modello e Classifica Top Seller / Flop Seller.",
                "quando_usarla": "Per scoprire quali scarpe o linee vendono di più o rendono di più.",
            },
            "04_Canali_Marketplace": {
                "titolo": "Canali & Marketplace",
                "percorso": "Analisi Dati > Canali & Marketplace",
                "scopo": "Dettaglio vendite suddivise per canale distributivo: Sito Web Diretto, Zalando ZFS, Amazon FBA, Marketplace esterni.",
                "quando_usarla": "Per confrontare la redditività e il volume dei diversi canali di vendita.",
            },
            "05_Nazioni": {
                "titolo": "Nazioni & Geografia",
                "percorso": "Analisi Dati > Nazioni & Geografia",
                "scopo": "Mappa e tabelle vendite per paese di spedizione (Italia, Germania, Francia, ecc.), con incidenza resi per nazione.",
                "quando_usarla": "Per analizzare l'espansione geografica e i mercati esteri.",
            },
            "06_Analisi_Resi": {
                "titolo": "Analisi Resi",
                "percorso": "Analisi Dati > Analisi Resi",
                "scopo": "Monitoraggio approfondito delle restituzioni: tasso di reso %, resi nel periodo, resi fuori periodo (resi extra da vendite passate) e motivi di reso.",
                "quando_usarla": "Per diagnosticare problemi di fit, difetti o canali ad alto tasso di reso.",
            },
            "07_Trova_SKU": {
                "titolo": "Trova SKU",
                "percorso": "Analisi Dati > Trova SKU",
                "scopo": "Ricerca istantanea di un singolo codice SKU o modello: scheda tecnica, foto, storico vendite, reso % e calzata.",
                "quando_usarla": "Per verificare le performance di una singola referenza.",
            },
            "08_Taglie": {
                "titolo": "Taglie per Brand",
                "percorso": "Analisi Dati > Taglie per Brand",
                "scopo": "Curve di calzata e percentuale di vendita per ogni numero/taglia di scarpa, evidenziando rotture di stock.",
                "quando_usarla": "Per ottimizzare il riassortimento dei numeri centrali o estremi.",
            },
            "09_Sell_Through": {
                "titolo": "Sell-Through",
                "percorso": "Analisi Dati > Sell-Through",
                "scopo": "Velocità di vendita dello stock iniziale e percentuale di smaltimento magazzino nel corso della stagione.",
                "quando_usarla": "Per pianificare saldi, promozioni o ordini di produzione.",
            },
        },
    },
    "Gestione Catalogo": {
        "descrizione": "Gestione del catalogo calzature, anagrafiche e listini.",
        "pagine": {
            "20_Catalogo_Panoramica": {
                "titolo": "Panoramica Catalogo",
                "percorso": "Gestione Catalogo > Panoramica Catalogo",
                "scopo": "Griglia visiva di tutte le collezioni con miniature e disponibilità anagrafica.",
            },
            "21_Catalogo_Articoli": {
                "titolo": "Articoli & Listini",
                "percorso": "Gestione Catalogo > Articoli & Listini",
                "scopo": "Scheda articolo con varianti colore, materiali e foto associate.",
            },
        },
    },
    "Gestione Foto": {
        "descrizione": "Archivio fotografico e associazione immagini a SKU.",
        "pagine": {
            "22_Foto_Archivio": {
                "titolo": "Archivio Fotografico",
                "percorso": "Gestione Foto > Archivio Fotografico",
                "scopo": "Galleria immagini ad alta risoluzione con ricerca per SKU o linea.",
            },
            "23_Foto_Caricamento": {
                "titolo": "Carica & Associa",
                "percorso": "Gestione Foto > Carica & Associa",
                "scopo": "Upload massivo di foto campionario con associazione automatica allo SKU.",
            },
        },
    },
    "Ferie": {
        "descrizione": "Gestione del personale, calendario presenze, ferie e permessi.",
        "pagine": {
            "24_Ferie_Calendario": {
                "titolo": "Calendario",
                "percorso": "Ferie > Calendario",
                "scopo": "Vista a calendario mensile di ferie e assenze di tutti i dipendenti per verificare sovrapposizioni.",
            },
            "25_Ferie_Registra": {
                "titolo": "Registra Ferie & Permessi",
                "percorso": "Ferie > Registra Ferie & Permessi",
                "scopo": "Modulo per Admin e Responsabili per inserire assenze/ferie concordate a voce. (Non sono previsti ROL distinti, tutto è gestito come ferie).",
            },
            "26_Ferie_Riepilogo": {
                "titolo": "Riepilogo",
                "percorso": "Ferie > Riepilogo",
                "scopo": "Tabella con totale giorni ferie spettanti, goduti e residui per ciascun lavoratore.",
            },
            "27_Ferie_Configurazioni": {
                "titolo": "Configurazioni",
                "percorso": "Ferie > Configurazioni",
                "scopo": "Anagrafica orari contrattuali e budget ferie annuo.",
            },
        },
    },
    "Export & Sistema": {
        "descrizione": "Strumenti di amministrazione, caricamento dati e diagnostica.",
        "pagine": {
            "00_Carica_Dati": {"titolo": "Carica Dati", "percorso": "Export & Sistema > Carica Dati", "scopo": "Importazione file ordini e resi Excel/CSV."},
            "15_Anagrafica": {"titolo": "Anagrafica Articoli", "percorso": "Export & Sistema > Anagrafica Articoli", "scopo": "Mapping correzioni manuali SKU, raggruppamento marchi e linee."},
            "10_Export_Dati": {"titolo": "Export Dati", "percorso": "Export & Sistema > Export Dati", "scopo": "Download dataset elaborati in Excel."},
            "14_Configurazioni": {"titolo": "Configurazioni", "percorso": "Export & Sistema > Configurazioni", "scopo": "Impostazioni parametri e tabelle di supporto."},
            "13_Correzioni_DB": {"titolo": "Correzioni DB", "percorso": "Export & Sistema > Correzioni DB", "scopo": "Correzioni puntuali record vendite e resi."},
            "11_Log_Riconciliazione": {"titolo": "Log Riconciliazione", "percorso": "Export & Sistema > Log Riconciliazione", "scopo": "Storico e diagnostica caricamenti."},
            "12_Account": {"titolo": "Account e Sicurezza", "percorso": "Export & Sistema > Account e Sicurezza", "scopo": "Modifica credenziali e profilo personale."},
            "16_Gestione_Ruoli": {"titolo": "Gestione Ruoli & Permessi", "percorso": "Export & Sistema > Gestione Ruoli & Permessi", "scopo": "Assegnazione permessi e ruoli di accesso aziendale."},
            "17_Nuovo_Utente": {"titolo": "Crea Nuovo Utente", "percorso": "Export & Sistema > Crea Nuovo Utente", "scopo": "Registrazione nuovi dipendenti nel portale."},
            "18_Stato_Connessioni": {"titolo": "Stato Connessioni", "percorso": "Export & Sistema > Stato Connessioni", "scopo": "Diagnostica salute DB SQLite, server LLM locale (8082) e server decisionale Rizzo Flow (8017)."},
        },
    },
}

# ---------------------------------------------------------------------------
# Guide Passo-Passo per i Workflow Tipici
# ---------------------------------------------------------------------------
WORKFLOW_GUIDES: dict[str, dict[str, Any]] = {
    "analizza_periodo": {
        "titolo": "Come analizzare i dati di un periodo specifico (es. Settembre 2026)",
        "passaggi": [
            "1. Accedi alla voce di menù **Analisi Dati > Dashboard** (per KPI generali) o **Analisi Dati > Y2Y Generale** (per il confronto con l'anno precedente).",
            "2. In alto nella pagina noterai la **Barra del Periodo (Topbar)** sempre visibile.",
            "3. Clicca sul campo **'Periodo di Analisi'** che apre il selettore del calendario.",
            "4. Imposta la **Data Inizio** (es. `01/09/2026`) e la **Data Fine** (es. `30/09/2026`).",
            "5. (Opzionale) Nel campo **'Perimetro'**, puoi selezionare `Totale`, `Canali Diretti` o uno specifico canale marketplace (es. Zalando ZFS).",
            "6. Clicca sul pulsante **'Applica'** sulla destra.",
            "7. La pagina aggiornerà immediatamente tutti i grafici, calcolando: Fatturato Netto, Paia Vendute, % di Reso e Confronto con lo stesso periodo dell'anno precedente.",
        ],
    },
    "confronto_anno_precedente": {
        "titolo": "Come confrontare le vendite con l'anno scorso (Y2Y)",
        "passaggi": [
            "1. Vai nel menù **Analisi Dati > Y2Y Generale**.",
            "2. Dalla **Topbar**, seleziona il periodo desiderato e premi **'Applica'**.",
            "3. Il sistema aggancia automaticamente lo stesso intervallo dell'anno precedente.",
            "4. Se desideri anche il confronto triennale, spunta il checkbox **'Includi Confronto Triennale (Y-2)'** prima di cliccare Applica.",
        ],
    },
    "trova_sku": {
        "titolo": "Come cercare la scheda e le performance di un singolo articolo / SKU",
        "passaggi": [
            "1. Vai nel menù **Analisi Dati > Trova SKU**.",
            "2. Digita il codice SKU o parte del nome del modello nella barra di ricerca.",
            "3. Visualizzerai: scheda tecnica, foto del catalogo, venduto netto, curve di calzata e percentuale di reso.",
        ],
    },
    "controllo_ferie_e_assenze": {
        "titolo": "Come verificare disponibilità e registrare ferie o permessi",
        "passaggi": [
            "1. **Policy Aziendale**: Le ferie e i permessi vanno SEMPRE concordati a voce con il responsabile prima di essere inseriti. I ROL non sono previsti: tutte le assenze orarie o giornaliere vengono gestite come 'ferie'.",
            "2. **Verifica Sovrapposizioni (per tutti i dipendenti)**: Consulta il menù **Ferie > Calendario** per controllare chi è già assente ed evitare accavallamenti nel proprio reparto/ruolo.",
            "3. **Registrazione (solo Admin o autorizzati)**: Gli admin o gli utenti con permessi dedicati possono registrare l'assenza confermata andando su **Ferie > Registra Ferie & Permessi** (o chiedendolo direttamente all'assistente bot).",
            "4. **Controllo Saldi**: Il riepilogo delle giornate residue è consultabile in **Ferie > Riepilogo**.",
        ],
    },
    "controllo_connessioni": {
        "titolo": "Come verificare lo stato dei server e del database",
        "passaggi": [
            "1. Vai nel menù **Export & Sistema > Stato Connessioni**.",
            "2. Troverai 3 schede: **Database SQLite**, **Server LLM Locale (8082)** e **Modello Decisionale (8017)**.",
            "3. Ciascun pannello mostra lo stato (🟢 Online / 🔴 Offline), il tempo di risposta e i record censiti.",
        ],
    },
}


# ---------------------------------------------------------------------------
# Snippet Compatto per il System Prompt del Chatbot
# ---------------------------------------------------------------------------
def get_site_knowledge_prompt_snippet() -> str:
    """Restituisce un blocco compatto di istruzioni sul portale EcomAnalysis da iniettare nel System Prompt."""
    return """
### Mappa del Portale EcomAnalysis e Guida Operativa all'Utente:
Sei anche il copilot esperto del sito **EcomAnalysis**. Quando l'utente ti chiede come effettuare operazioni, dove trovare report o come analizzare determinati dati, guidalo con precisione indicando la navigazione del menù.

🔴 **REGOLA FONDAMENTALE SUI NOMI DELLE PAGINE**:
- NON USARE MAI numeri o nomi di file .py (es. VIETATO dire '25 Registra', '01 Dashboard', '02 Y2Y Generale').
- Usa SEMPRE e SOLO il percorso visivo esatto del menù nel formato **`Gruppo > Voce`**.
  Esempi obbligatori:
  * Invece di '25 Registra' -> scrivi **Ferie > Registra Ferie & Permessi**
  * Invece di '24 Calendario' -> scrivi **Ferie > Calendario**
  * Invece di '26 Riepilogo' -> scrivi **Ferie > Riepilogo**
  * Invece di '01 Dashboard' -> scrivi **Analisi Dati > Dashboard**
  * Invece di '02 Y2Y' -> scrivi **Analisi Dati > Y2Y Generale**
  * Invece di '04 Canali' -> scrivi **Analisi Dati > Canali & Marketplace**
  * Invece di '06 Resi' -> scrivi **Analisi Dati > Analisi Resi**
  * Invece di '07 SKU' -> scrivi **Analisi Dati > Trova SKU**
  * Invece di '22 Foto' -> scrivi **Gestione Foto > Archivio Fotografico**
  * Invece di '18 Connessioni' -> scrivi **Export & Sistema > Stato Connessioni**

🔴 **POLICY AZIENDALE FERIE & PERMESSI**:
- I dipendenti NON possono inserire richieste autonome non concordate: ferie e permessi vanno SEMPRE concordati a voce con il responsabile.
- I dipendenti possono però verificare chi è in ferie per evitare sovrapposizioni consultando **Ferie > Calendario** (o chiedendolo a te in chat).
- Solo gli Admin o chi ha i permessi può registrare ferie/permessi in **Ferie > Registra Ferie & Permessi** (o chiederti di registrarle se autorizzati).
- I ROL non esistono in azienda: tutte le ore o giornate di assenza vengono imputate e gestite come "Ferie".

- **BARRA DEL PERIODO (TOPBAR)**: È la barra posizionata sempre in alto su tutte le pagine di **Analisi Dati**. Contiene:
  * `Periodo di Analisi`: selettore calendario per impostare Data Inizio e Data Fine (es. 01/09/2026 → 30/09/2026).
  * `Perimetro`: tendina per filtrare tra 'Totale', 'Canali Diretti' o singoli canali esterni (es. Zalando ZFS, Amazon FBA).
  * `Includi Confronto Triennale (Y-2)`: checkbox per abilitare il confronto a 3 anni.
  * Pulsante `Applica`: avvia il ricalcolo istantaneo di tutta la pipeline dati.

Fornisci sempre istruzioni numerate, chiare, pratiche e orientate all'azione.
""".strip()
