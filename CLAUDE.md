# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cos'è

Pannello di reportistica sell-out e-commerce (Python + Streamlit) per i vertici aziendali: i numeri devono essere coerenti in tutte le pagine, nell'API e nell'export. Stringhe UI, commenti e nomi di dominio sono in **italiano**.

## Comandi

```bash
pip install -r requirements.txt
streamlit run app.py                                   # app (entry point)
uvicorn api.main:app --host 127.0.0.1 --port 8001      # API dati FastAPI in sola lettura (docs: /api/docs)
python scripts/importa_db.py --dataset X.csv --resi Y.csv   # import da console (--stato, --svuota, --anagrafica)
python -m pytest tests                                 # tutti i test
python -m pytest tests/test_coerenza.py::test_nazioni_global_coincide_con_dashboard   # un singolo test
```

Non c'è un frontend React (rimosso: si resta su Streamlit). Segreti: `.streamlit/secrets.toml` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) e `api/.env` — mai committarli.

## Definizioni (da non cambiare senza chiedere)

Fonte unica: `core/metrics.py` (`kpi_reali`, `kpi_per_canale`, `compute_channel_kpi`).

- *Venduto*: righe con Data Pagamento nel periodo. Un reso conta nel venduto solo se la sua Data Reso è nello stesso periodo, altrimenti la riga resta **spedita**.
- *Resi fuori periodo*: Data Reso nel periodo e vendita fuori periodo. Un reso caricato senza il suo ordine è un ordine reale (ha Data Pagamento e Data Reso): segue le stesse regole, e se il DATASET arriva dopo `upsert_dataset` lo assorbe (`_unisci_resi_senza_ordine`) senza doppio conteggio. DataFrame separato con valori già negativi (`nettoNetto`). Il termine "standalone" non si usa più; resta solo nello schema SQLite (`is_rimborso_extra`, colonna `standalone` di `upload_log`) per compatibilità con DB esistenti.
- **Fatturato** = netto spedito − resi nel periodo − resi fuori periodo (prima voce della Dashboard). Ogni tabella aggregata deve sommare a questo valore: `tests/test_coerenza.py` lo verifica.
- Il numero di ordini non va mostrato nelle tabelle di dettaglio (non additivo); resta solo nei KPI di `metrics.py`/API. **Scontrino Medio** = netto spedito / ordini del venduto (rapporto, quindi ammesso a ogni livello: Dashboard, Y2Y, canali, marketplace, mensile).
- Variazioni: `report_builders.var_pct` = (curr − old)/|old|, **NaN con base zero** (mostrato "—"); le variazioni di percentuali (es. % reso) si esprimono in **punti** (`fmt_pp`). Le tabelle KPI già formattate come testo non vanno passate a `percent_col`/`NumberColumn` (Streamlit riinterpreta "3,3%" come 33).
- Etichette dei periodi (`formatting.etichetta_periodo`, `ui_helpers.period_labels`): nelle tabelle e nei nomi di colonna **l'anno dell'ultima data** del periodo ("2026", "2025"); nei grafici (`lunghe=True`) "2025/26" se il periodo è a cavallo d'anno, così novembre 2025 non sembra 2026.
- Streamlit ≥ 1.50: usare `width="stretch"`, non `use_container_width`.
- Periodo di default all'avvio: anno fiscale aziendale 1 nov → 31 ott che contiene oggi, limitato ai dati (`topbar.periodo_predefinito`; mese di inizio in `CONFIG.MESE_INIZIO_ANNO_FISCALE`).
- IVA fissa al 21% (scelta aziendale; `CONFIG.IVA2` predisposta ma non usata).

## Architettura

Flusso: **CSV → `core/engine.py` → DB SQLite (`data/ecombi.db`) → `pipeline.build_pipeline_from_db()` → `Pipeline` in `st.session_state["pipeline"]` → pagine**. Solo CSV con `;`, colonne posizionali (`CONFIG.COLS_DATASET`), niente TXT.

- `app.py`: menu a gruppi (`GRUPPI_MENU`) con `st.navigation(position="hidden")` registrata **prima** di `auth.require_session()`. Nuova pagina = file in `pages/NN_*.py` + `st.Page` + voce in `GRUPPI_MENU`. Prima di `pg.run()` disegna la **barra periodo** (`core/topbar.py`, sticky, su ogni pagina): è lei a costruire `st.session_state["pipeline"]` e le chiavi `sel_periodo_a`, `sel_periodo_b`, `periodo_*_label`, `sel_confronta_2anni`, `perimetro_label`; una pagina che cambia i dati (anagrafica, correzioni) imposta `rigenera_pipeline=True`.
- `core/auth.py`: login Supabase via REST + 2FA TOTP obbligatoria, sessione in cookie. Non chiamare `st.rerun()` nello stesso run di una scrittura cookie (eccezione: dopo `logout()`).
- `core/db.py`: id riga = hash del contenuto + contatore di occorrenza (ricarico idempotente). `upsert_resi` riconcilia al caricamento con cascata a due chiavi e FIFO; i resi senza match vengono inseriti (`is_rimborso_extra=1`). `query_period(conn, start, end, perimetro, sku_prefix=None)` ritorna `(venduto, resi_fuori_periodo)`. Tabella `anagrafica` salvata nel DB con chiave primaria `sku13`, aggiornamento con sostituzione (`ON CONFLICT(sku13) DO UPDATE SET`) e `sincronizza_genere_righe(conn)`. Cambiare id/chiavi invalida i DB esistenti (svuotare e ricaricare).
- `core/report_builders.py` + `aggregations.py`: tabelle per le pagine; passano **sempre** i resi fuori periodo (`resi_fp_*`) alle aggregazioni, altrimenti i totali non quadrano.
- `core/correzioni.py` (pagina Correzioni DB): trova e sostituisci su colonne descrittive (nazione, marketplace, collezioni, genere, tipo spedizione) con condizioni, anteprima, log e *regole salvate* riapplicate in `upsert_dataset`/`upsert_resi`. Colonne ammesse solo se NON entrano nell'id riga; per mkp/nazione ricalcola `key_composito`.
- `core/esplora.py` (pagina Articoli & Collezioni, tab «Esplora»): un'unica tabella con filtri a cascata Marketplace → Nazione → Brand → Collezione e raggruppamento a scelta; sostituisce le alberature (Streamlit non ha righe espandibili multilivello). `aggregate_hierarchical_custom`/`flatten_hierarchical_table` restano solo per il report API `y2y_collezioni`.
- `core/sku_search.py` (pagina Trova SKU, prefisso 7/9/13, periodo o intero DB con `FULL_DB_PERIOD`) e `core/export.py` (pagina Export Dati, colonne Anno/Mese/Scope, CSV/MD) usano le stesse funzioni dei report.
- `core/design_system.py`: tema e componenti condivisi (`page_setup`, `metric_cards`, `data_table`, `chart`, `it_num`): usarli nelle pagine.
- `api/main.py`: nessuna logica propria, riusa `core/`; auth `X-API-Key` o Bearer JWT Supabase.

## Test

`tests/conftest.py` crea un DB temporaneo e righe CSV sintetiche (`riga(...)`, 121 € lordi = 100 € netti). `test_pages_smoke.py` apre ogni pagina con Streamlit `AppTest`. Dopo ogni modifica ai calcoli rilancia l'intera suite. Per le modifiche grafiche (CSS, Plotly) la suite non basta: avvia l'app con dati sintetici e guardala nel browser (il server Streamlit tiene in cache i moduli `core/`: riavviarlo dopo le modifiche).

## Attenzioni

- Su Windows i file hanno spesso CRLF: se un `replace` testuale non trova la stringa, normalizza `\r\n`.
- Su Streamlit Cloud il filesystem è azzerato a ogni redeploy (il DB SQLite non è persistente).
