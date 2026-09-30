#!/usr/bin/env python3
"""
Importazione del DB da console (SSH/putty), senza passare dall'interfaccia Streamlit.

Riusa le STESSE funzioni della pagina "Carica Dati" (core.engine + core.db): la semantica è
identica — DATASET → upsert idempotente (ricaricare lo stesso file non duplica nulla),
RESI → riconciliazione con aggiornamento Spedito→Reso + righe standalone per i resi senza
spedito noto.

USO (lo script si posiziona da solo sulla root del repo, quindi la CWD non conta):

    python scripts/importa_db.py --dataset DATASET_2026.csv
    python scripts/importa_db.py --resi RESI_2026.csv
    python scripts/importa_db.py --dataset a.csv --dataset b.csv --resi r1.csv --resi r2.csv
    python scripts/importa_db.py --dataset grezzo.txt --col-sito 16   # TXT: correzione Nazione
    python scripts/importa_db.py --anagrafica ANAGRAFICA.csv --dataset DATASET.csv
    python scripts/importa_db.py --stato          # solo stato del DB, nessuna scrittura
    python scripts/importa_db.py --svuota         # zona pericolosa: svuota tutto il DB

Su SSH, per import lunghi che devono sopravvivere alla chiusura di Putty:

    nohup python scripts/importa_db.py --dataset DATASET.csv > import.log 2>&1 &
    tail -f import.log

oppure dentro una sessione tmux/screen. Il DB è sempre data/ecombi.db sotto la root del
repo (come quando l'app gira in Streamlit: --stato mostra il percorso effettivo).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Rende lo script eseguibile da qualunque directory e senza installazione del pacchetto:
# la root del repo finisce in sys.path e diventa la CWD (il percorso del DB, data/ecombi.db,
# è relativo, esattamente come quando l'app gira in Streamlit).
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from core import db, engine  # noqa: E402


def _fmt(n) -> str:
    return f"{n:,}".replace(",", ".")


def _progress(done: int, total: int, fase: str = "scrittura DB") -> None:
    if total:
        msg = f"  {fase}: {done:,}/{total:,} ({min(done / total, 1.0) * 100:.0f}%)".replace(",", ".")
    else:
        msg = f"  {fase}…"
    if sys.stdout.isatty():
        print("\r" + msg, end="", flush=True)
    else:
        print(msg, flush=True)


def _stampa_stato(conn) -> None:
    stats = db.get_stats(conn)
    print(f"DB: {db.DEFAULT_DB_PATH}")
    print(f"  Righe totali: {_fmt(stats['righe_totali'])}")
    print(f"  Spedite:      {_fmt(stats['spediti'])}")
    print(f"  Rese:         {_fmt(stats['resi'])}")
    print(f"  Rimborsi extra (standalone): {_fmt(stats['standalone'])}")
    if stats["data_min"]:
        print(f"  Copertura dati (Data Pagamento): dal {stats['data_min']} al {stats['data_max']}")
    else:
        print("  Nessun dato ancora caricato.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Importazione incrementale del DB EcomAnalysis "
                    "(stessa pipeline della pagina Carica Dati, senza Streamlit).")
    p.add_argument("--dataset", action="append", default=[], metavar="FILE",
                   help="File DATASET (CSV/TXT); ripetibile per più file")
    p.add_argument("--resi", action="append", default=[], metavar="FILE",
                   help="File RESI (CSV/TXT); ripetibile per più file")
    p.add_argument("--anagrafica", metavar="FILE",
                   help="File ANAGRAFICA (facoltativo: descrizioni articolo e genere)")
    p.add_argument("--col-sito", type=int, default=None, metavar="IDX",
                   help="Indice 0-based della colonna 'Sito esteso' per la correzione "
                        "Nazione sui TXT grezzi (default: nessuna correzione)")
    p.add_argument("--stato", action="store_true",
                   help="Mostra solo lo stato del DB ed esci (nessuna scrittura)")
    p.add_argument("--svuota", action="store_true",
                   help="ZONA PERICOLOSA: svuota completamente il DB PRIMA dell'import")
    args = p.parse_args()

    conn = db.connect()

    if args.stato:
        _stampa_stato(conn)
        return 0

    if args.svuota:
        try:
            conferma = input("Questo cancella TUTTE le righe del DB (data/ecombi.db). "
                             "Digita SVUOTA per confermare: ")
        except EOFError:
            print("stdin non interattivo (nohup/tmux?): per svuotare serve una console interattiva.")
            return 1
        if conferma.strip() != "SVUOTA":
            print("Annullato: il DB non è stato toccato.")
            return 1
        conn.executescript("DELETE FROM righe; DELETE FROM log_match; DELETE FROM upload_log;")
        conn.commit()
        print("DB svuotato.")

    richiesti = [(f, "DATASET") for f in args.dataset] + [(f, "RESI") for f in args.resi]

    if not richiesti:
        _stampa_stato(conn)
        print("Nessun file richiesto: usa --dataset e/o --resi (vedi --help).")
        return 0

    # Verifica esistenza PRIMA di iniziare: meglio fallire subito che a metà import.
    mancanti = [f for f, _ in richiesti if not os.path.isfile(f)]
    if mancanti:
        print("File non trovati: " + ", ".join(mancanti))
        return 1

    anagrafica = engine.load_anagrafica(args.anagrafica) if args.anagrafica else {}

    for path, tipo in richiesti:
        nome = os.path.basename(path)
        print(f"—— {tipo}: {nome}")
        raw = engine.read_raw_csv(path)
        if args.col_sito is not None:
            print(f"  Correzione Nazione (colonna Sito esteso idx={args.col_sito})…")
            engine.apply_nazione_correction_inplace(raw, args.col_sito)
        print(f"  Normalizzazione righe ({_fmt(len(raw))} righe)…")
        processed = engine.process_dataset(raw, anagrafica)
        del raw
        if processed.empty:
            print("  ⚠️ Nessuna riga valida nel file: saltato.")
            continue
        if tipo == "DATASET":
            stats = db.upsert_dataset(conn, processed, nome, progress=_progress)
            print()
            print(f"  ✅ {_fmt(stats['righe_nel_file'])} righe nel file, "
                  f"{_fmt(stats['righe_nuove'])} nuove, "
                  f"{_fmt(stats['righe_gia_presenti'])} già presenti (ignorate).")
        else:
            stats = db.upsert_resi(conn, processed, nome, progress=_progress)
            print()
            print(f"  ✅ {_fmt(stats['convertiti'])} convertite Spedito→Reso, "
                  f"{_fmt(stats['duplicati'])} già riconciliate (scartate), "
                  f"{_fmt(stats['standalone'])} rimborsi extra senza spedito noto.")

    print()
    _stampa_stato(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
