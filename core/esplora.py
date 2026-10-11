"""
Esplora per dimensioni — un'unica tabella filtrabile (sostituisce le tre alberature).

Filtri a cascata su Marketplace → Nazione → Brand → Collezione (ogni filtro offre solo i valori
compatibili con quelli scelti prima) e scelta delle dimensioni per cui raggruppare le righe.
Il Fatturato include i resi fuori periodo, come in tutto il resto dell'app: la somma delle righe
coincide con il Fatturato dei dati filtrati.
"""
from __future__ import annotations

import pandas as pd

from .report_builders import var_pct

# etichetta → colonna dei DataFrame prodotti da db.query_period (ordine = ordine della cascata)
DIMENSIONI = {"Marketplace": "mkp", "Nazione": "nazione", "Brand": "clzMappata", "Collezione": "clzOriginale"}
_MISURE = ["nettoNetto", "paiaSpedite", "paiaRese", "paiaNette"]
VUOTO = "—"


def filtra(df: pd.DataFrame | None, filtri: dict[str, list[str]]) -> pd.DataFrame | None:
    """`filtri` = {colonna: [valori ammessi]}; lista vuota = nessun filtro su quella colonna."""
    if df is None or df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    for col, valori in filtri.items():
        if valori:
            mask &= df[col].astype(str).replace("", VUOTO).isin(valori)
    return df[mask]


def opzioni(frames: list[pd.DataFrame | None], colonna: str, filtri_precedenti: dict[str, list[str]]) -> list[str]:
    """Valori disponibili per `colonna` nei dati già filtrati dalle scelte precedenti."""
    valori: set[str] = set()
    for f in frames:
        ff = filtra(f, filtri_precedenti)
        if ff is not None and not ff.empty:
            valori |= set(ff[colonna].astype(str).replace("", VUOTO).unique())
    return sorted(valori)


def _aggrega(venduto, resi_fp, colonne: list[str]) -> pd.DataFrame:
    pezzi = []
    for df in (venduto, resi_fp):
        if df is None or df.empty:
            continue
        w = pd.DataFrame({c: df[c].astype(str).replace("", VUOTO).to_numpy() for c in colonne})
        for m in _MISURE:
            w[m] = df[m].astype(float).to_numpy()
        pezzi.append(w)
    if not pezzi:
        return pd.DataFrame(columns=(colonne or ["_tot"]) + _MISURE)
    w = pd.concat(pezzi, ignore_index=True)
    if not colonne:
        w["_tot"] = "TOTALE"
        colonne = ["_tot"]
    g = w.groupby(colonne, sort=False, observed=True)[_MISURE].sum().reset_index()
    g["paiaNette"] = g["paiaNette"].clip(lower=0)               # mai negative
    return g


def tabella(corrente: tuple, precedente: tuple | None, filtri: dict[str, list[str]], raggruppa: list[str],
            y_curr: str, y_old: str) -> pd.DataFrame:
    """`corrente`/`precedente` = (venduto, resi fuori periodo). `raggruppa` = etichette di DIMENSIONI.
    Ritorna una riga per combinazione delle dimensioni scelte, ordinata per Fatturato."""
    colonne = [DIMENSIONI[d] for d in raggruppa]
    c = _aggrega(filtra(corrente[0], filtri), filtra(corrente[1], filtri), colonne)
    ha_old = precedente is not None and any(d is not None and not d.empty for d in precedente)
    o = _aggrega(filtra(precedente[0], filtri), filtra(precedente[1], filtri), colonne) if ha_old else None

    chiavi = colonne or ["_tot"]
    if o is not None:
        m = c.merge(o, on=chiavi, how="outer", suffixes=("", "_o")).fillna(0.0)
    else:
        m = c.copy()
        for x in _MISURE:
            m[x + "_o"] = 0.0
    if m.empty:
        return pd.DataFrame(columns=[*raggruppa, f"Paia Nette {y_curr}", f"% Reso {y_curr}", f"Fatturato {y_curr}"])

    tot_c, tot_o = m["nettoNetto"].sum(), m["nettoNetto_o"].sum()
    out = pd.DataFrame({d: m[col] for d, col in zip(raggruppa, colonne)}) if colonne else \
        pd.DataFrame({"Selezione": m["_tot"]})
    out[f"Paia Nette {y_curr}"] = m["paiaNette"]
    out[f"% Reso {y_curr}"] = (m["paiaRese"] / m["paiaSpedite"]).where(m["paiaSpedite"] > 0, 0.0)
    out[f"Fatturato {y_curr}"] = m["nettoNetto"]
    out[f"% Tot {y_curr}"] = m["nettoNetto"] / tot_c if tot_c > 0 else 0.0
    if o is not None:
        out[f"Paia Nette {y_old}"] = m["paiaNette_o"]
        out[f"% Reso {y_old}"] = (m["paiaRese_o"] / m["paiaSpedite_o"]).where(m["paiaSpedite_o"] > 0, 0.0)
        out[f"Fatturato {y_old}"] = m["nettoNetto_o"]
        out[f"% Tot {y_old}"] = m["nettoNetto_o"] / tot_o if tot_o > 0 else 0.0
        out["VAR% FATT"] = [var_pct(a, b) for a, b in zip(m["nettoNetto"], m["nettoNetto_o"])]
        out["VAR% PAIA"] = [var_pct(a, b) for a, b in zip(m["paiaNette"], m["paiaNette_o"])]
    return out.sort_values(f"Fatturato {y_curr}", ascending=False).reset_index(drop=True)
