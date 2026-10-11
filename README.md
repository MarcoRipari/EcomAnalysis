# Pannello Report E-commerce

Reportistica sell-out (porting da Google Apps Script a Python + Streamlit) su un DB SQLite
incrementale. I file CSV si caricano una volta sola; tutti i report leggono dal DB.

## Avvio

```bash
pip install -r requirements.txt
streamlit run app.py                                    # applicazione
uvicorn api.main:app --host 127.0.0.1 --port 8001       # API dati in sola lettura (opzionale)
python scripts/importa_db.py --dataset X.csv --resi Y.csv   # import da console
python -m pytest tests                                  # test di coerenza dei numeri
```

Segreti: `.streamlit/secrets.toml` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) per l'app; `api/.env`
per l'API (vedi `api/main.py`).

## Definizioni (valgono per tutta l'app, l'API e l'export — `core/metrics.py`)

- **Venduto del periodo**: righe con *Data Pagamento* nel periodo.
- **Reso nel periodo**: reso di una vendita del periodo con *Data Reso* nello stesso periodo.
  Se la Data Reso cade dopo il periodo, la riga resta **spedita** (es. vendita 10/01, reso 05/02,
  periodo gennaio → spedito).
- **Reso fuori periodo**: reso con *Data Reso* nel periodo ma vendita precedente (es. vendita
  28/12, reso 03/01, periodo gennaio).
- **Reso senza ordine nel DB** (file RESI caricato prima del DATASET): è un ordine reale, con
  la sua Data Pagamento e la sua Data Reso, e segue le regole sopra (vendita e reso nello
  stesso periodo si annullano). Quando poi arriva il DATASET con quell'ordine, la riga esistente
  lo assorbe senza essere contata due volte.
- **Fatturato** = fatturato netto spedito − resi nel periodo − resi fuori periodo.
  È il numero della prima voce della Dashboard; ogni tabella (marketplace, nazione, brand,
  SKU, mese, export) somma esattamente a questo valore.
- Il **numero di ordini** non è mostrato nelle tabelle di dettaglio (non è additivo).
- IVA fissa al 21% per tutte le nazioni (scelta aziendale; `CONFIG.IVA2` è predisposta per
  cambiarla: richiede di svuotare e ricaricare il DB).

## Struttura

```
app.py                  navigazione a gruppi + accesso (login Supabase + 2FA)
core/
  engine.py             lettura CSV (colonne posizionali) + normalizzazione righe
  db.py                 DB incrementale: upload DATASET/RESI, query per periodo (query_period)
  metrics.py            KPI e Fatturato (unica definizione)
  aggregations.py       aggregazioni per chiave / alberature
  report_builders.py    tabelle pronte per le pagine
  sku_search.py         analisi "Trova SKU"
  export.py             export CSV/Markdown per SCOPE, con Anno e Mese
  pipeline.py           build_pipeline_from_db: dati del periodo corrente e di confronto
pages/                  una pagina per report (menu in app.py → GRUPPI_MENU)
api/main.py             API REST in sola lettura (riusa core/)
scripts/importa_db.py   import da console
tests/                  regole di periodo, quadratura tra pagine, export, Trova SKU, smoke test pagine
```

Menu: **Sintesi** (Dashboard, Y2Y Generale) · **Performance** (Canali & Marketplace, Nazioni,
Articoli & Collezioni) · **Prodotto & Resi** (Trova SKU, Analisi Resi, Taglie, Sell-Through) ·
**Export & Sistema** (Carica Dati, Export Dati, Correzioni DB, Log Riconciliazione, Account).

In alto, su ogni pagina, c'è la **barra periodo** (perimetro, periodo, confronto a 2 anni, «Applica»):
resta visibile durante lo scroll. Alla prima apertura carica l'**anno fiscale aziendale** corrente
(1° novembre → 31 ottobre; es. oggi 11/10/2026 ⇒ 01/11/2025 → 31/10/2026), fino all'ultima data con dati.

## Correzioni DB

Trova e sostituisci sul DB: scegli la colonna (nazione, marketplace, collezioni, genere, tipo
spedizione), cosa cercare (uguale a, contiene, inizia/finisce con, è vuoto…), con cosa
sostituire (tutto il valore o solo il testo trovato), le condizioni aggiuntive (altre colonne,
intervallo di date) e guarda l'anteprima prima di applicare. Esempio: Nazione uguale a
`UNITED KIN` → `GB`. Spuntando «Salva anche come regola» la correzione viene riapplicata
automaticamente ai file caricati in futuro. Ogni correzione finisce nello storico.

## Caricamento dati

Solo file **CSV** con separatore `;`, stesso layout (posizionale, 0-based) per DATASET e RESI:

| # | Campo | # | Campo |
|---|---|---|---|
| 0 | Marketplace | 8 | Ordine |
| 1 | Nazione | 9 | Riga |
| 2 | Collezione | 10 | Valuta |
| 3 | Promo (1/vuoto) | 11 | Prezzo |
| 4 | Data Pagamento | 12 | Importo |
| 5 | Data Reso/Sped. | 13 | Quantità |
| 6 | Stato Riga | 14 | Coupon |
| 7 | Acquirente | 15 | Id.Articolo.Sku |

Date `dd/MM/yyyy` (`01/01/0001` = nessuna data), numeri con virgola decimale. Gli header
non sono letti. **ANAGRAFICA** (facoltativa): A=SKU, E=Collezione, F=Serie, G=Codice,
J=Descrizione, N=Genere. **BUYING** (solo Sell-Through): F=Codice, G=Variante, H=Colore,
L=Quantità, AV=Codice Cliente.

- Ricaricare lo stesso file non duplica nulla (id = hash del contenuto + contatore di occorrenza).
- Un file RESI converte in `Reso` le righe DATASET corrispondenti (prima chiave
  ordine+riga+sku+taglia, poi marketplace+nazione+acquirente+sku+taglia+importo, consumo FIFO).
  Un reso che non trova nessuna riga viene aggiunto come ordine reale (vedi sopra).
- La riconciliazione è scritta nello stato di ogni riga al caricamento; il periodo decide solo
  come leggerla.

## Trova SKU

Prefisso di 7 (codice), 9 o 13 caratteri (SKU completo), anche in minuscolo o con trattini.
Ambito: periodo selezionato o intero DB. Mostra KPI, composizione del Fatturato,
andamento mensile, taglie, marketplace, nazioni, canale, varianti, confronto con l'anno
precedente e le righe di dettaglio (export CSV).

## Export Dati

Pagina senza tabella a video: sceglie periodo/livello temporale (intero periodo o un mese per
riga) e scarica CSV o Markdown con colonne Anno, Mese, Scope, Marketplace, Nazione, Brand e
metriche. La somma di ogni SCOPE coincide con la riga GLOBAL.

## Persistenza

Il DB è `data/ecombi.db` (SQLite). Su Streamlit Community Cloud il filesystem viene azzerato a
ogni redeploy: per persistenza reale usare Turso (SQLite-compatibile) o Postgres.
Se hai caricato dati con una versione precedente del codice, svuota il DB (Carica Dati →
Zona pericolosa) e ricarica tutto, in modo che le righe riflettano la logica corrente.
