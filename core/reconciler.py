"""
Motore di riconciliazione RESI — porting 1:1 (stessa cascata di match, stesso ordine FIFO,
stessa semantica sul periodo) di reconcileResiConDataset() e chiaveComposita() in helpers.gs.

Nota di design: a differenza di process_dataset (vettorizzato pandas), qui si resta fedeli
a un ciclo Python "riga per riga" sulle RESI, perché la logica è intrinsecamente sequenziale
e stateful (consumo FIFO condiviso fra due indici di match diversi). Le RESI sono in pratica
sempre un sottoinsieme molto più piccolo del DATASET, quindi un ciclo Python puro resta
rapido anche con decine di migliaia di righe.
"""

from __future__ import annotations

from collections import defaultdict, deque
import random

import pandas as pd

from . import config as CFG


def chiave_composita(row) -> str:
    """
    Chiave per il match "campi invarianti": Mkp, Nazione, Acquirente, SKU13, Taglia,
    Importo Lordo (2 decimali). Porting fedele di chiaveComposita(): per gli acquirenti
    anonimizzati o i marketplace non inclusi nella whitelist, l'originale genera una chiave
    "spuria" con numeri casuali, che di fatto IMPEDISCE qualunque match per quelle righe
    (comportamento riprodotto qui esattamente, non è un bug della porting).
    """
    acquirente = row["acquirente"]
    mkp = row["mkp"]
    if acquirente in ("ANONYMIZED ANONYMIZED",) or mkp not in CFG.MKP_INCLUSI_MATCH_COMPOSITO:
        n1 = random.randint(10, 5009)
        n2 = random.randint(10, 5009)
        return f"{n1}|{row['nazione']}|{n2}|{row['sku13']}|{row['taglia']}|{row['lordoSpedito']:.2f}"
    return f"{mkp}|{row['nazione']}|{acquirente}|{row['sku13']}|{row['taglia']}|{row['lordoSpedito']:.2f}"


def _key_ordine(row) -> str:
    return f"{row['ordineId']}|{row['rigaOrdine']}|{row['sku13']}|{row['taglia']}"


def _is_date_in_period(date, period_start, period_end) -> bool:
    if pd.isna(date):
        return True
    if period_start is None or period_end is None:
        return True
    return period_start <= date <= period_end


def reconcile_resi_con_dataset(current_data: pd.DataFrame, resi_rows: pd.DataFrame,
                                period_start=None, period_end=None) -> dict:
    """
    MUTA IN-PLACE le righe di `current_data` convertite da Spedito a Reso.
    Ritorna { convertiti, duplicati, standalone, fuoriPeriodo } — le prime tre liste come
    liste di dict (log leggibile), `standalone` come lista di dict-riga completi (usati poi
    per i calcoli di fatturato "reale").
    """
    esito = {"convertiti": [], "duplicati": [], "standalone": [], "fuoriPeriodo": []}
    if resi_rows is None or resi_rows.empty:
        return esito

    consumed: set[int] = set()

    idx_ordine_sku: dict[str, deque] = defaultdict(deque)
    idx_composito: dict[str, deque] = defaultdict(deque)

    current_records = current_data.to_dict("records")
    for i, row in enumerate(current_records):
        idx_ordine_sku[_key_ordine(row)].append(i)
        idx_composito[chiave_composita(row)].append(i)

    def pop_fifo(idx, key):
        bucket = idx.get(key)
        if not bucket:
            return None
        while bucket:
            i = bucket.popleft()
            if i not in consumed:
                return i
        return None

    resi_records = resi_rows.to_dict("records")

    for resi_row in resi_records:
        key_ordine = _key_ordine(resi_row)
        idx_match = pop_fifo(idx_ordine_sku, key_ordine)
        modalita = "ORDINE+RIGA+SKU+TG" if idx_match is not None else None
        key_composito = key_ordine

        if idx_match is None:
            key_composito = chiave_composita(resi_row)
            idx_match = pop_fifo(idx_composito, key_composito)
            if idx_match is not None:
                modalita = "MKP+NAZ+ACQUIRENTE+SKU+TG+IMPORTO"

        if idx_match is not None:
            consumed.add(idx_match)
            row_dataset = current_records[idx_match]

            if row_dataset["isReso"]:
                esito["duplicati"].append({
                    "ordineId": row_dataset["ordineId"], "ordineIdResi": resi_row["ordineId"],
                    "sku13": str(row_dataset["sku13"]), "keyComp": key_composito, "modalita": modalita,
                })
            elif not _is_date_in_period(resi_row["dataReso"], period_start, period_end):
                esito["fuoriPeriodo"].append({
                    "ordineId": row_dataset["ordineId"], "ordineIdResi": resi_row["ordineId"],
                    "sku13": str(row_dataset["sku13"]), "keyComp": key_composito, "modalita": modalita,
                })
            else:
                row_dataset["isReso"] = True
                row_dataset["paiaRese"] = row_dataset["paiaSpedite"]
                row_dataset["paiaNette"] = 0.0
                row_dataset["nettoReso"] = row_dataset["nettoSpedito"]
                row_dataset["nettoNetto"] = 0.0
                row_dataset["lordoReso"] = row_dataset["lordoSpedito"]
                row_dataset["lordoNetto"] = 0.0
                row_dataset["matchedVia"] = modalita
                esito["convertiti"].append({
                    "ordineId": row_dataset["ordineId"], "ordineIdResi": resi_row["ordineId"],
                    "sku13": str(row_dataset["sku13"]), "keyComp": key_composito, "modalita": modalita,
                })
        elif not _is_date_in_period(resi_row["dataReso"], period_start, period_end):
            esito["fuoriPeriodo"].append({
                "ordineId": resi_row["ordineId"], "ordineIdResi": resi_row["ordineId"],
                "sku13": str(resi_row["sku13"]), "keyComp": key_composito, "modalita": "EXTRA_FUORI_PERIODO",
            })
        else:
            standalone_row = dict(resi_row)
            standalone_row.update({
                "isReso": True, "isRimborsoExtra": True,
                "paiaSpedite": 0.0, "paiaRese": resi_row["paiaSpedite"], "paiaNette": -resi_row["paiaSpedite"],
                "nettoSpedito": 0.0, "nettoReso": resi_row["nettoSpedito"], "nettoNetto": -resi_row["nettoSpedito"],
                "lordoSpedito": 0.0, "lordoReso": resi_row["lordoSpedito"], "lordoNetto": -resi_row["lordoSpedito"],
            })
            esito["standalone"].append(standalone_row)

    # Riscrive current_data con le righe (eventualmente) mutate, in-place sulle stesse colonne.
    mutated = pd.DataFrame(current_records, index=current_data.index)
    for colname in ["isReso", "paiaRese", "paiaNette", "nettoReso", "nettoNetto",
                     "lordoReso", "lordoNetto", "matchedVia"]:
        current_data[colname] = mutated[colname]

    esito["standalone"] = pd.DataFrame(esito["standalone"]) if esito["standalone"] else _empty_like(current_data)
    return esito


def _empty_like(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    if "isRimborsoExtra" not in cols:
        cols = cols + ["isRimborsoExtra"]
    return pd.DataFrame(columns=cols)
