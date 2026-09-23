"""
Motore di riconciliazione RESI — porting fedele (stessa cascata di match, stesso ordine FIFO,
stessa semantica sul periodo) di reconcileResiConDataset() e chiaveComposita() in helpers.gs.

v2 — riscritto per efficienza di memoria/CPU su dataset grandi (100k-300k+ righe):
- Le chiavi di match (ordine+riga+sku+taglia, e composito mkp+naz+acquirente+sku+taglia+importo)
  sono calcolate in modo VETTORIALE con pandas, non riga-per-riga in Python.
- Gli indici FIFO per il match sono costruiti con `groupby(...).indices` (vettoriale) invece
  che con un ciclo Python su tutte le righe di current_data.
- Il ciclo Python resta SOLO sulle righe di RESI (intrinsecamente sequenziale/stateful per il
  consumo FIFO condiviso fra i due indici), iterando su array numpy paralleli — niente
  `to_dict("records")`, niente dict-per-riga.
- L'aggiornamento delle righe convertite (Spedito -> Reso) avviene con UNA sola scrittura
  vettoriale via `.loc[indici]` alla fine, non ricostruendo l'intero DataFrame.
- Le righe che genererebbero una "chiave spuria" nell'originale (acquirente anonimizzato o
  marketplace non in whitelist — pensate per non trovare mai un match) usano qui un token
  univoco per riga invece di un numero casuale: stessa garanzia (zero collisioni), risultato
  deterministico invece che probabilistico, nessuna chiamata a random.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd

from . import config as CFG


def _key_ordine_series(df: pd.DataFrame) -> pd.Series:
    return (df["ordineId"].astype(str) + "|" + df["rigaOrdine"].astype(str) + "|" +
            df["sku13"].astype(str) + "|" + df["taglia"].astype(str))


def _key_composito_series(df: pd.DataFrame) -> pd.Series:
    whitelist = df["mkp"].isin(CFG.MKP_INCLUSI_MATCH_COMPOSITO) & (df["acquirente"] != "ANONYMIZED ANONYMIZED")
    lordo_cents = (df["lordoSpedito"].astype(float) * 100).round().astype("int64").astype(str)
    reale = (df["mkp"].astype(str) + "|" + df["nazione"].astype(str) + "|" + df["acquirente"].astype(str) + "|" +
             df["sku13"].astype(str) + "|" + df["taglia"].astype(str) + "|" + lordo_cents)
    spuria = "__SPURIOUS__" + pd.Series(np.arange(len(df)), index=df.index).astype(str)
    return reale.where(whitelist, spuria)


def _groupby_indices(key_series: pd.Series) -> dict:
    """{chiave: array di posizioni 0-based nell'ordine originale}, costruito in modo vettoriale
    (equivalente a Series.groupby(...).indices, senza passare per un DataFrame intermedio)."""
    df = pd.DataFrame({"k": key_series.to_numpy()})
    return df.groupby("k", sort=False).indices


def _is_date_in_period_np(date, period_start, period_end) -> bool:
    if pd.isna(date):
        return True
    if period_start is None or period_end is None:
        return True
    ts = pd.Timestamp(date)
    return period_start <= ts <= period_end


def _empty_like(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    if "isRimborsoExtra" not in cols:
        cols = cols + ["isRimborsoExtra"]
    return pd.DataFrame(columns=cols)


def reconcile_resi_con_dataset(current_data: pd.DataFrame, resi_rows: pd.DataFrame,
                                period_start=None, period_end=None) -> dict:
    """
    MUTA IN-PLACE le righe di `current_data` convertite da Spedito a Reso (via .loc vettoriale,
    un'unica volta alla fine). Ritorna { convertiti, duplicati, standalone, fuoriPeriodo }.
    """
    esito = {"convertiti": [], "duplicati": [], "standalone": [], "fuoriPeriodo": []}
    if resi_rows is None or resi_rows.empty or current_data.empty:
        esito["standalone"] = _empty_like(current_data)
        return esito

    current_data.reset_index(drop=True, inplace=True)
    n = len(current_data)

    key_ordine_curr = _key_ordine_series(current_data)
    key_composito_curr = _key_composito_series(current_data)

    idx_ordine_sku = {k: deque(v) for k, v in _groupby_indices(key_ordine_curr).items()}
    idx_composito = {k: deque(v) for k, v in _groupby_indices(key_composito_curr).items()}

    consumed = np.zeros(n, dtype=bool)

    def pop_fifo(idx: dict, key: str):
        bucket = idx.get(key)
        if not bucket:
            return None
        while bucket:
            i = bucket.popleft()
            if not consumed[i]:
                return i
        return None

    # Valori statici (non cambiano durante il loop: una riga del dataset "spedito" resta tale
    # finché non viene eventualmente convertita, e viene convertita al massimo una volta perché
    # rimossa dagli indici tramite `consumed`).
    orig_is_reso = current_data["isReso"].to_numpy()
    ordine_id_arr = current_data["ordineId"].to_numpy()
    sku13_arr = current_data["sku13"].to_numpy()

    key_ordine_resi = _key_ordine_series(resi_rows).to_numpy()
    key_composito_resi = _key_composito_series(resi_rows).to_numpy()
    resi_ordine_id = resi_rows["ordineId"].to_numpy()
    resi_sku13 = resi_rows["sku13"].to_numpy()
    resi_data_reso = resi_rows["dataReso"].to_numpy()
    m = len(resi_rows)

    matched_idx: list[int] = []
    matched_modalita: list[str] = []
    standalone_positions: list[int] = []

    for j in range(m):
        k_ord = key_ordine_resi[j]
        idx_match = pop_fifo(idx_ordine_sku, k_ord)
        modalita = "ORDINE+RIGA+SKU+TG" if idx_match is not None else None
        key_comp_used = k_ord

        if idx_match is None:
            key_comp_used = key_composito_resi[j]
            idx_match = pop_fifo(idx_composito, key_comp_used)
            if idx_match is not None:
                modalita = "MKP+NAZ+ACQUIRENTE+SKU+TG+IMPORTO"

        data_reso_j = resi_data_reso[j]
        in_periodo = _is_date_in_period_np(data_reso_j, period_start, period_end)

        if idx_match is not None:
            consumed[idx_match] = True
            if orig_is_reso[idx_match]:
                esito["duplicati"].append({
                    "ordineId": ordine_id_arr[idx_match], "ordineIdResi": resi_ordine_id[j],
                    "sku13": str(sku13_arr[idx_match]), "keyComp": key_comp_used, "modalita": modalita,
                })
            elif not in_periodo:
                esito["fuoriPeriodo"].append({
                    "ordineId": ordine_id_arr[idx_match], "ordineIdResi": resi_ordine_id[j],
                    "sku13": str(sku13_arr[idx_match]), "keyComp": key_comp_used, "modalita": modalita,
                })
            else:
                matched_idx.append(idx_match)
                matched_modalita.append(modalita)
                esito["convertiti"].append({
                    "ordineId": ordine_id_arr[idx_match], "ordineIdResi": resi_ordine_id[j],
                    "sku13": str(sku13_arr[idx_match]), "keyComp": key_comp_used, "modalita": modalita,
                })
        elif not in_periodo:
            esito["fuoriPeriodo"].append({
                "ordineId": resi_ordine_id[j], "ordineIdResi": resi_ordine_id[j],
                "sku13": str(resi_sku13[j]), "keyComp": key_comp_used, "modalita": "EXTRA_FUORI_PERIODO",
            })
        else:
            standalone_positions.append(j)

    # --- scrittura vettoriale unica delle righe convertite ---
    if matched_idx:
        mi = np.asarray(matched_idx)
        current_data.loc[mi, "isReso"] = True
        current_data.loc[mi, "paiaRese"] = current_data.loc[mi, "paiaSpedite"].to_numpy()
        current_data.loc[mi, "paiaNette"] = 0.0
        current_data.loc[mi, "nettoReso"] = current_data.loc[mi, "nettoSpedito"].to_numpy()
        current_data.loc[mi, "nettoNetto"] = 0.0
        current_data.loc[mi, "lordoReso"] = current_data.loc[mi, "lordoSpedito"].to_numpy()
        current_data.loc[mi, "lordoNetto"] = 0.0
        current_data.loc[mi, "matchedVia"] = matched_modalita

    if standalone_positions:
        st_df = resi_rows.iloc[standalone_positions].copy()
        st_df["isReso"] = True
        st_df["isRimborsoExtra"] = True
        pS = resi_rows["paiaSpedite"].to_numpy()[standalone_positions]
        nS = resi_rows["nettoSpedito"].to_numpy()[standalone_positions]
        lS = resi_rows["lordoSpedito"].to_numpy()[standalone_positions]
        st_df["paiaSpedite"] = 0.0
        st_df["paiaRese"] = pS
        st_df["paiaNette"] = -pS
        st_df["nettoSpedito"] = 0.0
        st_df["nettoReso"] = nS
        st_df["nettoNetto"] = -nS
        st_df["lordoSpedito"] = 0.0
        st_df["lordoReso"] = lS
        st_df["lordoNetto"] = -lS
        esito["standalone"] = st_df.reset_index(drop=True)
    else:
        esito["standalone"] = _empty_like(current_data)

    return esito
