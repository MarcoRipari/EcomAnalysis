# Pannello Report E-commerce — porting Python/Streamlit

Porting del sistema di reportistica sell-out da Google Apps Script (backend.gs, helpers.gs,
tables.gs, reports.gs, menu.gs) a Python + Streamlit, pensato per l'hosting su Streamlit
Cloud con repository GitHub.

## Struttura

```
app.py                      # Home: upload file, scelta perimetro, esecuzione pipeline
core/
  config.py                 # CONFIG (mappe collezioni/nazioni, tassi cambio, IVA, layout colonne)
  engine.py                 # Lettura CSV + processDataset (vettorizzato pandas)
  metrics.py                # calculateGlobalMetricsDetailed, computeChannelKPI, periodo
  reconciler.py             # Motore riconciliazione RESI (FIFO, stessa cascata di match)
  aggregations.py           # aggregateByKey, alberature, taglie per brand, carryover
  report_builders.py        # Traduce i dati aggregati in DataFrame per la UI
  sellthrough.py            # Parsing BUYING + calcolo sell-through
  pipeline.py               # Orchestrazione (equivalente a showUnifiedGenerator)
  ui_helpers.py             # Helper Streamlit (column_config, guard pagina)
pages/
  1_📊_Dashboard.py
  2_📈_Y2Y_Generale.py
  3_🌳_Y2Y_Collezioni.py
  4_🔢_Y2Y_Codici.py
  5_♻️_Carryover.py
  6_👟_Taglie.py
  7_🔄_Analisi_Resi.py
  8_🔍_Log_Riconciliazione.py
  9_📦_Sell_Through.py
requirements.txt
```

## Avvio locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy su Streamlit Cloud

1. Pusha questa cartella su un repository GitHub.
2. Su share.streamlit.io collega il repo, imposta `app.py` come entry point.
3. Nessun secret richiesto: l'app lavora solo su file caricati a runtime dall'utente
   (nessun dato salvato server-side).

## File di input attesi (CSV, separatore `;`, stesso layout in tutti e 4)

Layout POSIZIONALE (0-based), identico a `CONFIG.COLS_DATASET` dell'originale — gli header
del CSV non vengono letti per nome (possono avere encoding sporco, non importa):

| # | Campo             | # | Campo        |
|---|--------------------|---|--------------|
| 0 | Marketplace/Sito   | 8 | Ordine       |
| 1 | Nazione            | 9 | Riga         |
| 2 | Collezione         |10 | Valuta       |
| 3 | Promo (1/vuoto)    |11 | Prezzo       |
| 4 | Data Pagamento     |12 | Importo      |
| 5 | Data Reso/Sped.    |13 | Quantità     |
| 6 | Stato Riga         |14 | Coupon       |
| 7 | Acquirente         |15 | Id.Articolo.Sku |

Date in formato `dd/MM/yyyy` (o `01/01/0001` per "nessuna data"), numeri con virgola
decimale (`89,00`).

**ANAGRAFICA** (facoltativa, stesso principio posizionale): colonna A=SKU, E=Collezione,
F=Serie, G=Codice/variante, J=Descrizione, N=Genere. Se non caricata, i report funzionano
comunque ma senza descrizioni articolo e con genere sempre "NON CLASSIFICATO".

**BUYING** (solo per la pagina Sell-Through): colonna F=Codice, G=Variante, H=Colore,
L=Quantità, AV=Codice Cliente.

## Note di fedeltà al porting

- **Colonne per posizione, non per nome header**: l'export CSV può avere header con
  encoding corrotto; il mapping resta quello di `CONFIG.COLS_DATASET`.
- **Date placeholder**: `01/01/0001` diventa `NaT` (nessuna data), replicando il comportamento
  di Google Sheets con una data non valida.
- **Aliquota IVA sempre al 21%**: l'originale usa `masterData.iva = CONFIG.IVA` (che contiene
  SOLO `'IT': 0.21`) con fallback `CONFIG.DEFAULT_IVA = 0.21`. Il risultato pratico è che il
  netto viene sempre calcolato al 21%, indipendentemente dalla nazione — `CONFIG.IVA2` (le
  aliquote per paese) non è mai referenziato in `processDataset`. Il porting riproduce
  **fedelmente** questo comportamento. Se è un bug dell'originale da correggere, segnalalo:
  è una modifica di una riga in `core/engine.py` (`iva_rate = nazione.map(CFG.IVA2)...`).
- **Riconciliazione RESI**: stessa cascata a due indici (ORDINE+RIGA+SKU+TG, poi
  MKP+NAZ+ACQUIRENTE+SKU+TG+IMPORTO), stesso consumo FIFO, stessa gestione del periodo
  (`fuoriPeriodo`), stessa "chiave spuria" per acquirenti anonimizzati/marketplace non
  whitelisted in `chiave_composita` (impedisce volutamente il match per quelle righe, non è
  un bug del porting).

## Cosa NON è stato portato 1:1

- La formattazione a fogli Excel (colori cella, merge, chart nativi Sheets) è sostituita da
  componenti Streamlit nativi (`st.dataframe` con `column_config`, `plotly` per il grafico
  dell'andamento mensile). I **dati e la logica di calcolo** sono invece portati fedelmente.
- Le foto articolo (`=IMAGE(...)` nell'originale) sono renderizzate con
  `st.column_config.ImageColumn` sullo stesso URL (`repository.falc.biz`).
- Nessuna scrittura su Google Drive/Sheets: ogni report vive solo nella sessione Streamlit;
  se serve l'export, aggiungere un pulsante "Scarica CSV/Excel" per singola tabella (rapido
  da aggiungere con `st.download_button` + `df.to_csv()` — dimmi se lo vuoi già pronto).

## Prossimi passi suggeriti

- Se i CSV superano ~150-200k righe e i tempi di caricamento diventano un problema su
  Streamlit Cloud (risorse limitate sul tier gratuito), valuta di cachare `process_dataset`
  con `st.cache_data` chiavizzato sull'hash del file, e/o di pre-processare in Parquet.
- Pulsanti di export (CSV/Excel) per singola tabella, se ti servono per condividerle fuori
  dall'app.
- Se in produzione l'aliquota IVA per nazione (`IVA2`) va effettivamente usata invece del fisso
  21%, è la singola riga indicata sopra.
