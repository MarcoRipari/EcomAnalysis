"""
Report builders — porting della LOGICA (non della UI a fogli/celle) dei moduli in
reports.gs e tables.gs. Ogni funzione ritorna strutture dati semplici (dict / DataFrame)
pronte per essere renderizzate da una pagina Streamlit con st.dataframe / st.metric /
st.plotly_chart, al posto delle chiamate SpreadsheetApp dell'originale.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from . import aggregations as agg
from . import config as CFG
from . import formatting as fmt

import logging
logging.basicConfig(level=logging.INFO)

def var_pct(curr: float, old: float) -> float:
    """Porting di getVar/varFatt: (curr/old - 1), con fallback se old==0."""
    if old != 0:
        return (curr / old) - 1
    return 1.0 if curr > 0 else 0.0


def img_url(sku13: str) -> str:
    return CFG.IMAGE_URL_TEMPLATE.format(img=str(sku13).lower())


# --------------------------------------------------------------------------------------
# Blocco KPI generico — porting di drawKPIBlockGeneric
# --------------------------------------------------------------------------------------

def kpi_block(kc: dict, ko: dict, y_curr: int, y_old: int) -> pd.DataFrame | None:
    """Tabella KPI con METRICHE DI TIPO DIVERSO sulle righe (valuta/conteggio/percentuale) e i
    periodi sulle colonne: i valori sono già formattati come stringa (stile italiano), perché
    il column_config di Streamlit si applica per colonna e non può gestire tipi diversi riga
    per riga nella stessa colonna."""
    if kc["ordini"] == 0 and ko["ordini"] == 0:
        return None
    rows = [
        ("FATTURATO NETTO REALE", kc["fattReale"], ko["fattReale"], "currency"),
        ("TOTALE ORDINI", kc["ordini"], ko["ordini"], "number"),
        ("PAIA NETTE VENDUTE", kc["paiaNette"], ko["paiaNette"], "number"),
        ("VALORE MEDIO PAIO", kc["valMedio"], ko["valMedio"], "currency"),
        ("% RESO", kc["percReso"], ko["percReso"], "percent"),
    ]
    data = [(m, fmt.fmt(c, k), fmt.fmt(o, k), fmt.fmt_percent(var_pct(c, o))) for m, c, o, k in rows]
    return pd.DataFrame(data, columns=["Metrica", str(y_curr), str(y_old), "Var % Y2Y"])


# --------------------------------------------------------------------------------------
# Tabella comparativa Y2Y — porting di drawComparativeTable
# --------------------------------------------------------------------------------------

def comparative_table(agg_current: dict, agg_old: dict, y_curr: int, y_old: int,
                       sort_type: str = "fatturatoNetto") -> pd.DataFrame:
    all_keys = set(agg_current["map"].keys()) | set(agg_old["map"].keys())
    empty = {"ordini": 0, "paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0, "fatturatoNetto": 0.0}

    rows = []
    for key in all_keys:
        c = agg_current["map"].get(key, empty)
        o = agg_old["map"].get(key, empty)
        var_fatt = var_pct(c["fatturatoNetto"], o["fatturatoNetto"])
        p_reso_c = c["paiaRese"] / c["paiaSpedite"] if c["paiaSpedite"] > 0 else 0.0
        rows.append([key, c["fatturatoNetto"], o["fatturatoNetto"], var_fatt,
                     c["paiaNette"], o["paiaNette"], c["ordini"], o["ordini"], p_reso_c,
                     c.get(sort_type, 0)])

    cols = ["Chiave", f"Fatt.Netto {y_curr}", f"Fatt.Netto {y_old}", "VAR% FATT",
            f"Paia Nette {y_curr}", f"Paia Nette {y_old}", f"Ordini {y_curr}", f"Ordini {y_old}",
            f"% Reso {y_curr}", "_sort"]
    df = pd.DataFrame(rows, columns=cols).sort_values("_sort", ascending=False).drop(columns="_sort")
    return df.reset_index(drop=True)


def single_year_table(aggregator: dict, y_curr: int, sort_type: str = "fatturatoNetto") -> pd.DataFrame:
    """Porting di drawSingleYearTable (usato nella Dashboard, un solo anno)."""
    rows = []
    for key, c in aggregator["map"].items():
        p_reso = c["paiaRese"] / c["paiaSpedite"] if c["paiaSpedite"] > 0 else 0.0
        scontrino = c["fatturatoSpedito"] / c["ordini"] if c["ordini"] > 0 else 0.0
        rows.append([key, c["ordini"], c["paiaSpedite"], c["paiaRese"], p_reso,
                     c["paiaNette"], scontrino, c["fatturatoNetto"], c.get(sort_type, 0)])
    cols = ["Chiave", "Ordini", "Paia Spedite", "Paia Rese", "% Reso", "Paia Nette",
            "Scontrino Medio", f"Fatturato Netto {y_curr}", "_sort"]
    df = pd.DataFrame(rows, columns=cols).sort_values("_sort", ascending=False).drop(columns="_sort")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Top articoli — porting di drawTopArticoliY2Y (con confronto Y2Y) e della sezione
# "TOP ARTICOLI" della Dashboard (solo anno corrente, livello SKU13)
# --------------------------------------------------------------------------------------

def top_articoli_y2y(current_data: pd.DataFrame, old_data: pd.DataFrame, anagrafica: dict,
                      y_curr: int, y_old: int, top_n: int = 20) -> pd.DataFrame:
    has_old = old_data is not None and not old_data.empty

    def build(df, is_current, m):
        if df.empty:
            return
        g = df.groupby("sku7", sort=False).agg(
            pCNet=("paiaNette", "sum"), pCSped=("paiaSpedite", "sum"),
            pCRes=("paiaRese", "sum"), f=("nettoNetto", "sum"),
            clz=("clzOriginale", "first"), sku13=("sku13", "first"),
        )
        for cod, r in g.iterrows():
            entry = m.setdefault(cod, {"pCNet": 0, "pCSped": 0, "pCRes": 0, "fC": 0, "fO": 0,
                                        "clz": r["clz"], "img": str(r["sku13"]).lower()})
            if is_current:
                entry["pCNet"] += r["pCNet"]; entry["pCSped"] += r["pCSped"]
                entry["pCRes"] += r["pCRes"]; entry["fC"] += r["f"]
            else:
                entry["fO"] += r["f"]

    map_data: dict = {}
    build(current_data, True, map_data)
    if has_old:
        build(old_data, False, map_data)

    rows = []
    for cod, d in map_data.items():
        desc = anagrafica.get(cod, {}).get("desc", "-")
        p_reso_c = d["pCRes"] / d["pCSped"] if d["pCSped"] > 0 else 0.0
        var_fatt = var_pct(d["fC"], d["fO"]) if has_old else None
        row = {"Foto": img_url(d["img"]), "Codice": cod, "Descrizione": desc,
               f"Paia Nette {y_curr}": d["pCNet"], f"Fatt.Netto {y_curr}": d["fC"]}
        if has_old:
            row[f"Fatt.Netto {y_old}"] = d["fO"]
            row["VAR% FATT"] = var_fatt
        row[f"% Reso {y_curr}"] = p_reso_c
        row["_sort"] = d["fC"]
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("_sort", ascending=False).drop(columns="_sort").head(top_n).reset_index(drop=True)


def top_articoli_dashboard(current_data: pd.DataFrame, anagrafica: dict, top_n: int = 5000) -> pd.DataFrame:
    """Porting della tabella Top Articoli della Dashboard (livello SKU13, solo anno corrente)."""
    agg_sku = agg.aggregate_by_key(current_data, "sku13")
    rows = []
    for sku, item in agg_sku["map"].items():
        desc = anagrafica.get(sku, {}).get("desc") or anagrafica.get(sku[:7], {}).get("desc", "-")
        p_reso = item["paiaRese"] / item["paiaSpedite"] if item["paiaSpedite"] > 0 else 0.0
        rows.append({
            "Foto": img_url(item["img"]), "Articolo": f"{sku.upper()} — {desc}",
            "Collezione": item["clzOriginale"], "Paia Spedite": item["paiaSpedite"],
            "Paia Rese": item["paiaRese"], "% Reso": p_reso, "Paia Nette": item["paiaNette"],
            "Fatturato Netto": item["fatturatoNetto"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("Paia Nette", ascending=False).head(top_n).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Andamento mensile — porting di drawMonthlyTrendModule
# --------------------------------------------------------------------------------------

def monthly_trend(current_data: pd.DataFrame, old_data: pd.DataFrame,
                   resi_standalone_current: pd.DataFrame, resi_standalone_old: pd.DataFrame,
                   y_curr: int, y_old: int) -> pd.DataFrame:

    def with_mese_vendita(df):
        if df.empty:
            return df
        out = df.copy()
        out["_mese"] = out["dataVendita"].dt.month.fillna(0).astype(int)
        return out

    def with_mese_reso(df):
        if df.empty:
            return df
        out = df.copy()
        d = out["dataReso"].fillna(out.get("dataVendita"))
        out["_mese"] = pd.to_datetime(d).dt.month.fillna(0).astype(int)
        return out

    agg_c = agg.aggregate_by_key(with_mese_vendita(current_data), "_mese")
    agg_o = agg.aggregate_by_key(with_mese_vendita(old_data), "_mese")
    agg_sc = agg.aggregate_by_key(with_mese_reso(resi_standalone_current), "_mese")
    agg_so = agg.aggregate_by_key(with_mese_reso(resi_standalone_old), "_mese")

    empty = {"ordini": 0, "paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0,
             "fatturatoSpedito": 0.0, "fatturatoNetto": 0.0}

    rows = []
    for m in range(1, 13):
        key = str(m)
        c = agg_c["map"].get(key, empty)
        o = agg_o["map"].get(key, empty)
        sc = agg_sc["map"].get(key, {"paiaRese": 0.0, "paiaNette": 0.0, "fatturatoNetto": 0.0})
        so = agg_so["map"].get(key, {"paiaNette": 0.0, "fatturatoNetto": 0.0})

        fatt_reale_c = c["fatturatoNetto"] + sc["fatturatoNetto"]
        fatt_reale_o = o["fatturatoNetto"] + so["fatturatoNetto"]
        paia_nette_reale_c = c["paiaNette"] + sc["paiaNette"]
        paia_nette_reale_o = o["paiaNette"] + so["paiaNette"]
        paia_rese_reale_c = c["paiaRese"] + sc["paiaRese"]

        if fatt_reale_c == 0 and fatt_reale_o == 0 and c["ordini"] == 0:
            continue

        var_fatt = var_pct(fatt_reale_c, fatt_reale_o)
        p_reso = paia_rese_reale_c / c["paiaSpedite"] if c["paiaSpedite"] > 0 else 0.0
        scontrino_medio = c["fatturatoSpedito"] / c["ordini"] if c["ordini"] > 0 else 0.0

        rows.append([CFG.MESI_IT[m - 1], fatt_reale_c, fatt_reale_o, var_fatt, c["ordini"],
                     paia_nette_reale_c, p_reso, scontrino_medio, paia_nette_reale_o])

    cols = ["Mese", f"Fatt.Netto Reale {y_curr}", f"Fatt.Netto Reale {y_old}", "VAR% FATT",
            f"Ordini {y_curr}", f"Paia Nette {y_curr}", f"% Reso {y_curr}",
            f"Scontrino Medio {y_curr}", f"Paia Nette {y_old}"]
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------------------
# Report mensile dinamico con stagioni SS/FW — "Andamento Mese per Mese".
# A differenza di monthly_trend (gennaio→dicembre fisso), qui i mesi partono dal mese
# di inizio del periodo scelto e arrivano al mese finale (es. periodo 2025-11-01 →
# 2026-11-01 = Novembre 2025 … Novembre 2026), attraversando l'anno di confine.
# La stagione è puramente DATA-BASED (nessun attributo di prodotto):
#   SS = Spring/Summer = 01 marzo → 31 agosto
#   FW = Fall/Winter   = 01 settembre → 28-29 febbraio
# L'etichetta di una stagione FW usa gli anni che attraversa: settembre 2025 e
# gennaio 2026 appartengono entrambi a "FW 25/26".
# --------------------------------------------------------------------------------------

SS_MESI = frozenset({3, 4, 5, 6, 7, 8})      # marzo → agosto
FW_MESI = frozenset({9, 10, 11, 12, 1, 2})   # settembre → febbraio


def _stagione_label(anno: int, mese: int) -> str:
    """Etichetta della stagione di appartenenza di un mese: 'SS 2026' oppure 'FW 25/26'."""
    if mese in SS_MESI:
        return f"SS {anno}"
    inizio = anno - 1 if mese in (1, 2) else anno      # la FW parte a settembre
    return f"FW {str(inizio)[-2:]}/{str(inizio + 1)[-2:]}"


def _mesi_periodo(da, a) -> list[tuple[int, int]]:
    """Tutti i (anno, mese) del periodo [da, a] al mese (estremi inclusi), anche
    attraverso il cambio d'anno: 2025-11-01 → 2026-11-01 = 13 mesi da (2025, 11) a (2026, 11)."""
    mesi: list[tuple[int, int]] = []
    y, m = da.year, da.month
    while (y, m) <= (a.year, a.month):
        mesi.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return mesi


def _stats_mensili(venduto: pd.DataFrame, standalone: pd.DataFrame | None,
                   mesi: list[tuple[int, int]]) -> dict[tuple[int, int], dict]:
    """(anno, mese) → metriche del mese. Stessa semantica di monthly_trend: il fatturato
    netto reale include i rimborsi standalone attribuiti al mese di dataReso (fallback
    dataVendita); gli ordini sono i ordineId distinti non vuoti delle sole vendite."""
    stats = {ym: {"fatturato": 0.0, "ordini": 0, "paiaSpedite": 0.0, "paiaRese": 0.0,
                  "paiaNette": 0.0} for ym in mesi}

    v = venduto
    if v is not None and not v.empty and "dataVendita" in v.columns:
        v = v[v["dataVendita"].notna()].copy()
    if v is not None and not v.empty:
        v["_ym"] = list(zip(v["dataVendita"].dt.year.astype(int),
                            v["dataVendita"].dt.month.astype(int)))
        v["_ord"] = v["ordineId"].where(v["ordineId"] != "")
        g = v.groupby("_ym").agg({"nettoNetto": "sum", "paiaSpedite": "sum", "paiaRese": "sum",
                                  "paiaNette": "sum", "_ord": "nunique"})
        for ym, r in g.iterrows():
            if ym in stats:
                stats[ym]["fatturato"] += float(r["nettoNetto"])
                stats[ym]["ordini"] = int(r["_ord"])
                stats[ym]["paiaSpedite"] += float(r["paiaSpedite"])
                stats[ym]["paiaRese"] += float(r["paiaRese"])
                stats[ym]["paiaNette"] += float(r["paiaNette"])

    s = standalone
    if s is not None and not s.empty and "dataReso" in s.columns:
        s = s.copy()
        d = pd.to_datetime(s["dataReso"].fillna(s.get("dataVendita")))
        s["_ym"] = list(zip(d.dt.year.astype(int), d.dt.month.astype(int)))
        g = s.groupby("_ym").agg({"nettoNetto": "sum", "paiaRese": "sum", "paiaNette": "sum"})
        for ym, r in g.iterrows():
            if ym in stats:
                stats[ym]["fatturato"] += float(r["nettoNetto"])
                stats[ym]["paiaRese"] += float(r["paiaRese"])
                stats[ym]["paiaNette"] += float(r["paiaNette"])

    for st in stats.values():
        st["percReso"] = st["paiaRese"] / st["paiaSpedite"] if st["paiaSpedite"] > 0 else 0.0
    return stats


def _agg_stagioni(stats: dict[tuple[int, int], dict]) -> dict[str, dict]:
    """Somma le statistiche mensili per stagione (etichetta 'SS 2026' / 'FW 25/26'),
    mantenendo l'ordine cronologico di prima comparsa. NB: gli ordini di stagione sono
    la somma degli ordini distinti mese per mese (un ordine a cavallo di due mesi verrebbe
    contato due volte, ai fini del trend è trascurabile e coerente tra i periodi)."""
    stagioni: dict[str, dict] = {}
    for (y, m), st in stats.items():
        lab = _stagione_label(y, m)
        d = stagioni.setdefault(lab, {"fatturato": 0.0, "ordini": 0, "paiaSpedite": 0.0,
                                      "paiaRese": 0.0, "paiaNette": 0.0, "mesi": 0})
        for k in ("fatturato", "ordini", "paiaSpedite", "paiaRese", "paiaNette"):
            d[k] += st[k]
        d["mesi"] += 1
    for d in stagioni.values():
        d["percReso"] = d["paiaRese"] / d["paiaSpedite"] if d["paiaSpedite"] > 0 else 0.0
    return stagioni


def monthly_season_report(da, a,
                           periodi: list[tuple[str, pd.DataFrame, pd.DataFrame]]
                           ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Report "Mese per Mese" con stagioni SS/FW, a finestra mobile sul periodo scelto.

    `periodi` = [(etichetta, venduto, rimborsi standalone), …]: la posizione i corrisponde
    al periodo scelto spostato di −i anni (0 = periodo scelto, 1 = anno−1, 2 = anno−2),
    quindi ogni riga-mese confronta lo stesso mese degli anni precedenti (con confronti=0
    la tabella mostra solo il periodo scelto, senza colonne di variazione).

    Ritorna (df_mesi, df_stagioni):
      df_mesi   — una riga per ogni mese da month(da) a month(a), con: Fatturato Netto,
                  Ordini, Paia Nette e % Reso del periodo corrente; per ogni anno di
                  confronto: Fatturato Netto e VAR% di fatturato/ordini/paia;
      df_stagioni — una riga per stagione (SS/FW) toccata dal periodo, con le stesse
                  metriche e la colonna "Mesi nel periodo" (mesi presenti su 6).
    """
    mesi = _mesi_periodo(da, a)
    labels = [p[0] for p in periodi]

    # statistiche mensili per ogni periodo (mesi spostati di −posizione anni)
    stats = []
    for i, (_lbl, v, s) in enumerate(periodi):
        stats.append(_stats_mensili(v, s, [(y - i, m) for (y, m) in mesi]))

    # ---- tabella mese per mese --------------------------------------------------------
    righe = []
    for idx, (y, m) in enumerate(mesi):
        # Etichetta del mese: SOLO il nome ("Settembre"), senza anno: il confronto e'
        # posizionale (stesso mese del periodo scelto, -1 anno, -2 anni) quindi l'anno
        # e' implicito e la finestra puo' attraversare il cambio d'anno (lug -> apr).
        # Guardia: se la finestra supera i 12 mesi (estremi inclusi) il nome del mese si
        # ripeterebbe sull'asse del grafico: in quel caso si tiene "Mese YYYY".
        etichetta = CFG.MESI_IT[m - 1] if len(mesi) <= 12 else f"{CFG.MESI_IT[m - 1]} {y}"
        riga: dict = {"Mese": etichetta, "Stagione": _stagione_label(y, m)}
        cur = stats[0].get((y, m))
        riga[f"Fatturato Netto {labels[0]}"] = cur["fatturato"]
        riga[f"Ordini {labels[0]}"] = cur["ordini"]
        riga[f"Paia Nette {labels[0]}"] = cur["paiaNette"]
        riga[f"% Reso {labels[0]}"] = cur["percReso"]
        for i in range(1, len(periodi)):
            old = stats[i].get((y - i, m))
            riga[f"Fatturato Netto {labels[i]}"] = old["fatturato"]
            riga[f"VAR% FATT vs {labels[i]}"] = var_pct(cur["fatturato"], old["fatturato"])
            riga[f"VAR% ORDINI vs {labels[i]}"] = var_pct(cur["ordini"], old["ordini"])
            riga[f"VAR% PAIA vs {labels[i]}"] = var_pct(cur["paiaNette"], old["paiaNette"])
        righe.append(riga)
    df_mesi = pd.DataFrame(righe)

    # ---- tabella stagioni SS / FW -----------------------------------------------------
    # NB: il confronto stagioni accoppia per POSIZIONE, non per etichetta: nel periodo
    # corrente la stagione si chiama "FW 25/26", nel periodo−1 anno "FW 24/25" — sono
    # gli stessi mesi spostati di un anno, quindi la k-esima stagione del periodo
    # corrente confronta la k-esima del periodo di confronto.
    stag = [_agg_stagioni(st) for st in stats]          # una per periodo
    ordini = [list(s.keys()) for s in stag]             # etichette in ordine cronologico

    righe = []
    for k, lab in enumerate(ordini[0]):
        cur = stag[0][lab]
        riga: dict = {"Stagione": lab, "Mesi nel periodo": f"{cur['mesi']}/6"}
        riga[f"Fatturato Netto {labels[0]}"] = cur["fatturato"]
        riga[f"Ordini {labels[0]}"] = cur["ordini"]
        riga[f"Paia Nette {labels[0]}"] = cur["paiaNette"]
        riga[f"% Reso {labels[0]}"] = cur["percReso"]
        for i in range(1, len(periodi)):
            old = stag[i].get(ordini[i][k]) if k < len(ordini[i]) else None
            if old is None:
                continue
            riga[f"Fatturato Netto {labels[i]}"] = old["fatturato"]
            riga[f"VAR% FATT vs {labels[i]}"] = var_pct(cur["fatturato"], old["fatturato"])
            riga[f"VAR% ORDINI vs {labels[i]}"] = var_pct(cur["ordini"], old["ordini"])
            riga[f"VAR% PAIA vs {labels[i]}"] = var_pct(cur["paiaNette"], old["paiaNette"])
        righe.append(riga)
    df_stagioni = pd.DataFrame(righe)
    return df_mesi, df_stagioni


# --------------------------------------------------------------------------------------
# Comparativa Codici (SKU7) — porting di generateComparativaCodiciModulo
# --------------------------------------------------------------------------------------

def comparativa_codici(current_data: pd.DataFrame, old_data: pd.DataFrame, anagrafica: dict,
                        y_curr: int, y_old: int) -> pd.DataFrame:
    map_data: dict = {}

    def build(df, is_current):
        if df.empty:
            return
        g = df.groupby("sku7", sort=False).agg(
            pNet=("paiaNette", "sum"), pSped=("paiaSpedite", "sum"), pRes=("paiaRese", "sum"),
            f=("nettoNetto", "sum"), clz=("clzOriginale", "first"), sku13=("sku13", "first"),
        )
        for cod, r in g.iterrows():
            e = map_data.setdefault(cod, {"pCNet": 0, "pCSped": 0, "pCRes": 0, "fC": 0,
                                           "pONet": 0, "pOSped": 0, "pORes": 0, "fO": 0,
                                           "clz": r["clz"], "img": str(r["sku13"]).lower()})
            if is_current:
                e["pCNet"] += r["pNet"]; e["pCSped"] += r["pSped"]; e["pCRes"] += r["pRes"]; e["fC"] += r["f"]
            else:
                e["pONet"] += r["pNet"]; e["pOSped"] += r["pSped"]; e["pORes"] += r["pRes"]; e["fO"] += r["f"]

    build(current_data, True)
    build(old_data, False)

    rows = []
    for cod, d in map_data.items():
        desc = anagrafica.get(cod, {}).get("desc", "-")
        var_fatt = var_pct(d["fC"], d["fO"])
        p_reso_c = d["pCRes"] / d["pCSped"] if d["pCSped"] > 0 else 0.0
        p_reso_o = d["pORes"] / d["pOSped"] if d["pOSped"] > 0 else 0.0
        rows.append([img_url(d["img"]), cod, d["clz"], desc, d["pCNet"], p_reso_c, d["fC"],
                     d["pONet"], p_reso_o, d["fO"], var_fatt])

    cols = ["Foto", "Codice", "Collezione", "Descrizione", f"Paia Net {y_curr}", f"% Reso {y_curr}",
            f"Fatt. Net {y_curr}", f"Paia Net {y_old}", f"% Reso {y_old}", f"Fatt. Net {y_old}", "VAR% FATT"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    return df.sort_values(f"Fatt. Net {y_curr}", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Tabella gerarchica (Collezioni / Carryover) — porting di drawCustomHierarchicalTable
# --------------------------------------------------------------------------------------

def flatten_hierarchical_table(current_tree: dict, old_tree: dict, level_names: list[str]) -> pd.DataFrame:
    max_depth = len(level_names)
    curr_total = current_tree["total"] or 0.0
    old_total = old_tree["total"] or 0.0
    rows = []

    def traverse(curr_nodes, old_nodes, depth):
        all_keys = set((curr_nodes or {}).keys()) | set((old_nodes or {}).keys())
        empty_node = {"paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0, "fatturatoNetto": 0.0, "kids": {}}

        def sort_key(k):
            n = (curr_nodes or {}).get(k, empty_node)
            return n["fatturatoNetto"]

        for key in sorted(all_keys, key=sort_key, reverse=True):
            c_node = (curr_nodes or {}).get(key, empty_node)
            o_node = (old_nodes or {}).get(key, empty_node)

            p_c = c_node["fatturatoNetto"] / curr_total if curr_total > 0 else 0.0
            p_o = o_node["fatturatoNetto"] / old_total if old_total > 0 else 0.0
            v_f = var_pct(c_node["fatturatoNetto"], o_node["fatturatoNetto"]) if o_node["fatturatoNetto"] else 0.0
            v_p = var_pct(c_node["paiaNette"], o_node["paiaNette"]) if o_node["paiaNette"] else 0.0
            p_reso_c = c_node["paiaRese"] / c_node["paiaSpedite"] if c_node["paiaSpedite"] > 0 else 0.0
            p_reso_o = o_node["paiaRese"] / o_node["paiaSpedite"] if o_node["paiaSpedite"] > 0 else 0.0

            indent = "\u2003\u2003" * depth
            label = indent + ("📁 " if depth == 0 else "🏷️ ") + (key.upper() if depth == 0 else key)

            rows.append({
                "Voce": label, "Depth": depth,
                "Paia Net Curr": c_node["paiaNette"], "% Reso Curr": p_reso_c,
                "Fatt. Netto Curr": c_node["fatturatoNetto"], "% Tot Curr": p_c,
                "Paia Net Old": o_node["paiaNette"], "% Reso Old": p_reso_o,
                "Fatt. Netto Old": o_node["fatturatoNetto"], "% Tot Old": p_o,
                "VAR% FATT": v_f, "VAR% PAIA": v_p,
            })
            if depth < max_depth - 1:
                traverse(c_node["kids"], o_node["kids"], depth + 1)

    traverse(current_tree["tree"], old_tree["tree"], 0)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Analisi Resi (status per collezione) — porting di generateResiModulo
# --------------------------------------------------------------------------------------

def resi_status(current_data: pd.DataFrame) -> pd.DataFrame:
    agg_data = agg.aggregate_by_key(current_data, "clzMappata")
    soglia = 0.30
    rows = []
    for clz, item in agg_data["map"].items():
        v, r, fatt = item["paiaSpedite"], item["paiaRese"], item["fatturatoNetto"]
        perc_reso = r / v if v > 0 else 0.0
        if perc_reso >= 1:
            status = "🔴 CRITICO (100%)"
        elif perc_reso > 0.7:
            status = "🔴 CRITICO"
        elif perc_reso > soglia + 0.1:
            status = "🟠 PESSIMO"
        elif perc_reso > soglia:
            status = "🟡 MONITORARE"
        elif perc_reso > soglia * 0.8:
            status = "🔵 STABILE"
        else:
            status = "🟢 OTTIMO"
        rows.append(["📁 " + clz, v, r, perc_reso, fatt, status])
    df = pd.DataFrame(rows, columns=["Brand/Collezione", "Paia Spedite", "Paia Rese", "% Reso",
                                      "Fatturato Netto", "Status"])
    if df.empty:
        return df
    return df.sort_values("% Reso", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Taglie per Brand — porting di generateTaglieModulo (aggregateByTagliaPerBrand)
# --------------------------------------------------------------------------------------

def _sort_taglie(taglie: list[str]) -> list[str]:
    def key(t):
        try:
            return (0, int(t))
        except ValueError:
            return (1, t)
    return sorted(taglie, key=key)


def taglie_tables(current_data: pd.DataFrame) -> dict:
    """{ brand: { gruppo: DataFrame[Taglia, Paia Nette, % su gruppo, % Reso, Fatturato Netto] } }"""
    by_brand = agg.aggregate_by_taglia_per_brand(current_data)
    result: dict = {}
    for brand in sorted(by_brand.keys()):
        result[brand] = {}
        for gruppo in sorted(by_brand[brand].keys()):
            tag_map = by_brand[brand][gruppo]
            taglie = _sort_taglie(list(tag_map.keys()))
            tot_gruppo = sum(tag_map[t]["paiaNette"] for t in taglie)
            rows = []
            for t in taglie:
                d = tag_map[t]
                perc_su_gruppo = d["paiaNette"] / tot_gruppo if tot_gruppo > 0 else 0.0
                perc_reso = d["paiaRese"] / d["paiaSpedite"] if d["paiaSpedite"] > 0 else 0.0
                rows.append([t, d["paiaNette"], perc_su_gruppo, perc_reso, d["fatturatoNetto"]])
            result[brand][gruppo] = pd.DataFrame(
                rows, columns=["Taglia", "Paia Nette", f"% su {gruppo}", "% Reso", "Fatturato Netto"])
    return result


# --------------------------------------------------------------------------------------
# Comparativa Nazioni — nuova pagina "Nazioni"
# --------------------------------------------------------------------------------------

def nazioni_disponibili(*dfs: pd.DataFrame) -> list[str]:
    naz = set()
    for df in dfs:
        if df is not None and not df.empty:
            naz |= set(df["nazione"].astype(str).unique())
    return sorted(naz)


def nazioni_metrics(venduto: pd.DataFrame, standalone: pd.DataFrame, nazioni: list[str]) -> pd.DataFrame:
    """Una riga per nazione selezionata, con le metriche richieste per la pagina Nazioni."""
    rows = []
    for naz in nazioni:
        if naz == "GLOBAL":
            v = venduto if not venduto.empty else None
            s = standalone if (standalone is not None and not standalone.empty) else None
        else:
            v = venduto[venduto["nazione"].astype(str) == naz] if not venduto.empty else None
            s = standalone[standalone["nazione"].astype(str) == naz] if (standalone is not None and not standalone.empty) else None

        fatt_venduto = v["nettoNetto"].sum() if (v is not None and not v.empty) else 0.0
        fatt_extra = s["nettoNetto"].sum() if (s is not None and not s.empty) else 0.0
        ordini = v.loc[v["ordineId"] != "", "ordineId"].nunique() if (v is not None and not v.empty) else 0
        paia_sped = v["paiaSpedite"].sum() if (v is not None and not v.empty) else 0.0
        paia_rese_in = v["paiaRese"].sum() if (v is not None and not v.empty) else 0.0
        paia_nette = v["paiaNette"].sum() if (v is not None and not v.empty) else 0.0
        paia_rese_out = s["paiaRese"].sum() if (s is not None and not s.empty) else 0.0
        perc_reso = paia_rese_in / paia_sped if paia_sped > 0 else 0.0

        rows.append([naz, fatt_venduto + fatt_extra, ordini, paia_nette, paia_rese_in, paia_rese_out, perc_reso])

    cols = ["Nazione", "Fatturato Netto Totale", "Totale Ordini", "Totale Paia Nette",
            "Paia Rese (spedito nel range)", "Paia Rese (spedito fuori range)", "% Reso"]
    return pd.DataFrame(rows, columns=cols)


def nazioni_brand_share(venduto: pd.DataFrame, nazione: str) -> pd.DataFrame:
    """Share % del fatturato netto per brand (clzMappata), per una singola nazione."""
    if venduto.empty:
        return pd.DataFrame(columns=["Brand", "Fatturato Netto", "Share %"])

    if nazione == "GLOBAL":
        v = venduto
    else:
        v = venduto[venduto["nazione"].astype(str) == nazione]
    
    if v.empty:
        return pd.DataFrame(columns=["Brand", "Fatturato Netto", "Share %"])
    # ordineId vuoto non deve contare come ordine: NaN viene ignorato da nunique
    # (stesso guard usato in nazioni_unified_report e aggregate_by_key)
    v = v.copy()
    v["_ord"] = v["ordineId"].where(v["ordineId"] != "")
    g = v.groupby("clzMappata", sort=False, observed=True).agg({
            "lordoSpedito": "sum",
            "_ord": "nunique",
            "nettoNetto": "sum",
            "paiaSpedite": "sum",
            "paiaRese": "sum",
            "paiaNette": "sum"
        }).reset_index()
    g = g.rename(columns={"clzMappata": "Brand", "nettoNetto": "Fatturato Netto", "paiaSpedite": "Paia spedite", "paiaRese": "Paia rese", "paiaNette": "Paia nette", "_ord": "Ordini"})
    tot = g["Fatturato Netto"].sum()
    g["Share %"] = g["Fatturato Netto"] / tot if tot != 0 else 0.0
    g["% Reso"] = np.where(g["Paia spedite"] > 0, g["Paia rese"] / g["Paia spedite"], 0.0)
    g["Scontrino Medio"] = np.where(g["Ordini"] > 0, g["lordoSpedito"] / g["Ordini"], 0.0)
    
    g = g.drop(columns=["lordoSpedito"])

    cols_order = [
        "Brand",
        "Ordini",
        "Fatturato Netto",
        "Share %",
        "Scontrino Medio",
        "Paia spedite",
        "Paia rese",
        "Paia nette",
        "% Reso"
    ]
    return g[cols_order].sort_values("Fatturato Netto", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Report unificato Marketplace × Nazione × Brand — pagina "Nazioni" (confronto 3 anni)
# --------------------------------------------------------------------------------------

# --- Margini & commissioni marketplace (predisposizione, ATTUALMENTE DISATTIVATA) --------
# Struttura pronta per il calcolo del margine nel report unificato. Quando i dati delle
# commissioni marketplace saranno disponibili: compilare COMMISSIONI_MKP con la quota di
# commissione applicata al fatturato netto per marketplace (es. {"ZALANDO": 0.25}) e
# impostare ABILITA_MARGINI = True: il report aggiungerà le colonne "Margine Lordo" (€) e
# "Margine %". Negli scope con marketplace GLOBAL la commissione è la media pesata sul
# fatturato dei marketplace sottostanti, quindi anche le righe GLOBAL restano coerenti.
# Finché i dati non ci sono, le colonne non compaiono nel report.
ABILITA_MARGINI = False
COMMISSIONI_MKP: dict[str, float] = {}   # marketplace -> commissione sul netto (0–1)
COMMISSIONE_DEFAULT = 0.0                # marketplace assente dalla mappa


def nazioni_unified_report(periodi: list[tuple[str, pd.DataFrame]], nazioni_scelte: list[str]) -> pd.DataFrame:
    """
    Report unificato Marketplace × Nazione × Brand: per ogni periodo in `periodi` (lista di
    coppie (etichetta, DataFrame venduto)) genera una riga per ogni combinazione marketplace ×
    nazione × brand presente nei dati (scope DETAIL) più tutte le aggregazioni in cui una o più
    dimensioni sono "collassate" a GLOBAL, identificate dallo Scope:

    | Marketplace | Nazione | Brand  | Scope                |
    | ----------- | ------- | ------ | -------------------- |
    | Zalando     | IT      | Naturino | DETAIL             |
    | Zalando     | IT      | GLOBAL | MARKETPLACE_COUNTRY  |
    | Zalando     | GLOBAL  | Naturino | MARKETPLACE_BRAND  |
    | GLOBAL      | IT      | Naturino | COUNTRY_BRAND      |
    | Zalando     | GLOBAL  | GLOBAL | GLOBAL_MARKETPLACE  |
    | GLOBAL      | IT      | GLOBAL | GLOBAL_COUNTRY      |
    | GLOBAL      | GLOBAL  | Naturino | GLOBAL_BRAND       |
    | GLOBAL      | GLOBAL  | GLOBAL | GLOBAL              |

    Le nazioni di dettaglio sono limitate a `nazioni_scelte` (il valore "GLOBAL" del selettore
    viene ignorato, perché lì indica l'aggregato); le righe aggregate GLOBAL sono sempre
    generate, indipendentemente dal selettore.

    KPI sui soli dati venduto (stessa semantica di nazioni_brand_share):
      Fatturato Netto = somma nettoNetto · Ordini = ordineId distinti non vuoti
      Scontrino Medio = lordoSpedito / Ordini · Reso % = paiaRese / paiaSpedite
      Reso % (valore) = nettoReso / nettoSpedito — entrambi positivi per costruzione in
      engine.py (nettoNetto = nettoSpedito - nettoReso): è il peso del reso sul valore
      spedito, complementare a Reso % che invece è a paia.
    Share % = Fatturato Netto della riga / Fatturato Netto GLOBAL dello stesso anno: peso
    della combinazione (marketplace, nazione, brand o aggregato) sul totale azienda del
    periodo — la riga GLOBAL vale quindi 100%.
    Var % Fatturato YoY / Var % Ordini YoY = confronto con la riga dello stesso scope e
    della stessa combinazione del periodo precedente (i periodi sono attesi in ordine
    [corrente, -1 anno, -2 anni], quindi il periodo i confronta con il periodo i+1). Se la
    combinazione non esisteva l'anno prima, la Var % resta vuota (NaN) invece di forzare un
    +100%. La somma delle righe NON fa il totale azienda per Ordini e Scontrino Medio
    (ordini deduplicati per ordineId); il Fatturato invece somma esattamente.
    Con ABILITA_MARGINI = True (vedi sopra) vengono aggiunte "Margine Lordo" e "Margine %".
    """
    cols = ["Anno", "Marketplace", "Nazione", "Brand", "Fatturato Netto", "Share %",
            "Scontrino Medio", "Ordini", "Paia spedite", "Paia rese", "Paia nette",
            "Reso %", "Reso % (valore)", "Var % Fatturato YoY", "Var % Ordini YoY", "Scope"]
    if ABILITA_MARGINI:
        cols = cols[:-1] + ["Margine Lordo", "Margine %", "Scope"]

    nazioni_specifiche = {n for n in (nazioni_scelte or []) if n != "GLOBAL"}
    rows: list[dict] = []

    for label, df in periodi:
        if df is None or df.empty:
            continue

        work = df.copy()
        work["_mkp"] = work["mkp"].astype(str)
        work["_naz"] = work["nazione"].astype(str)
        work["_brand"] = work["clzMappata"].fillna("").astype(str).replace("", "ALTRO")
        # ordineId vuoto non deve contare come ordine: NaN viene ignorato da nunique
        work["_ord"] = work["ordineId"].where(work["ordineId"] != "")
        # commissione per riga: permette la media pesata sul fatturato negli scope aggregati
        if ABILITA_MARGINI:
            work["_nettoComm"] = work["nettoNetto"] * work["_mkp"].map(
                lambda m: COMMISSIONI_MKP.get(m, COMMISSIONE_DEFAULT))

        def _agg_by(keys: list[str]) -> pd.DataFrame:
            aggs = {
                #"fatt": ("nettoNetto", "sum"),
                "fatt": ("fattReale", "sum"),
                "lordo": ("lordoSpedito", "sum"),
                "fSped": ("nettoSpedito", "sum"),
                "fReso": ("nettoReso", "sum"),
                "spedite": ("paiaSpedite", "sum"),
                "rese": ("paiaRese", "sum"),
                "nette": ("paiaNette", "sum"),
                "ordini": ("_ord", "nunique"),
            }
            if ABILITA_MARGINI:
                aggs["fComm"] = ("_nettoComm", "sum")
            return work.groupby(keys, sort=False, observed=True).agg(**aggs)

        g_det = _agg_by(["_mkp", "_naz", "_brand"])   # DETAIL
        g_mc = _agg_by(["_mkp", "_naz"])              # MARKETPLACE_COUNTRY
        g_mb = _agg_by(["_mkp", "_brand"])            # MARKETPLACE_BRAND
        g_m = _agg_by(["_mkp"])                       # GLOBAL_MARKETPLACE
        g_cb = _agg_by(["_naz", "_brand"])            # COUNTRY_BRAND
        g_c = _agg_by(["_naz"])                       # GLOBAL_COUNTRY
        g_gb = _agg_by(["_brand"])                    # GLOBAL_BRAND
        tot = {                                       # GLOBAL
            #"fatt": float(work["nettoNetto"].sum()),
            "fatt": float(work["fattReale"].sum()),
            "lordo": float(work["lordoSpedito"].sum()),
            "fSped": float(work["nettoSpedito"].sum()),
            "fReso": float(work["nettoReso"].sum()),
            "spedite": float(work["paiaSpedite"].sum()),
            "rese": float(work["paiaRese"].sum()),
            "nette": float(work["paiaNette"].sum()),
            "ordini": int(work["_ord"].nunique()),
        }
        if ABILITA_MARGINI:
            tot["fComm"] = float(work["_nettoComm"].sum())

        def _row(scope: str, mkp: str, naz: str, brand: str, k, share: float):
            ordini = int(k["ordini"])
            spedite = float(k["spedite"])
            rese = float(k["rese"])
            f_sped = float(k["fSped"])
            row = {
                "Anno": label,
                "Marketplace": mkp, "Nazione": naz, "Brand": brand,
                "Fatturato Netto": float(k["fatt"]),
                "Share %": share,
                "Scontrino Medio": (float(k["lordo"]) / ordini) if ordini > 0 else 0.0,
                "Ordini": ordini,
                "Paia spedite": spedite,
                "Paia rese": rese,
                "Paia nette": float(k["nette"]),
                "Reso %": (rese / spedite) if spedite > 0 else 0.0,
                # nettoReso è positivo (vedi engine.py): rapporto diretto sul netto spedito
                "Reso % (valore)": (float(k["fReso"]) / f_sped) if f_sped > 0 else 0.0,
                "Scope": scope,
            }
            if ABILITA_MARGINI:
                f_comm = float(k["fComm"])
                row["Margine Lordo"] = row["Fatturato Netto"] - f_comm
                row["Margine %"] = (row["Margine Lordo"] / row["Fatturato Netto"]) if row["Fatturato Netto"] > 0 else 0.0
            rows.append(row)

        def _share(num: float, den: float) -> float:
            return num / den if den > 0 else 0.0

        # DETAIL — singola combinazione marketplace × nazione × brand
        for (m, c, b), k in g_det.iterrows():
            if c in nazioni_specifiche:
                _row("DETAIL", m, c, b, k, _share(k["fatt"], tot["fatt"]))

        # MARKETPLACE_COUNTRY — tutti i brand di (marketplace, nazione)
        for (m, c), k in g_mc.iterrows():
            if c in nazioni_specifiche:
                _row("MARKETPLACE_COUNTRY", m, c, "GLOBAL", k, _share(k["fatt"], tot["fatt"]))

        # MARKETPLACE_BRAND — brand su tutti i Paesi del marketplace
        for (m, b), k in g_mb.iterrows():
            _row("MARKETPLACE_BRAND", m, "GLOBAL", b, k, _share(k["fatt"], tot["fatt"]))

        # COUNTRY_BRAND — brand in nazione su tutti i marketplace
        for (c, b), k in g_cb.iterrows():
            if c in nazioni_specifiche:
                _row("COUNTRY_BRAND", "GLOBAL", c, b, k, _share(k["fatt"], tot["fatt"]))

        # GLOBAL_MARKETPLACE — tutto il marketplace
        for m, k in g_m.iterrows():
            _row("GLOBAL_MARKETPLACE", m, "GLOBAL", "GLOBAL", k, _share(k["fatt"], tot["fatt"]))

        # GLOBAL_COUNTRY — tutto il business della nazione
        for c, k in g_c.iterrows():
            if c in nazioni_specifiche:
                _row("GLOBAL_COUNTRY", "GLOBAL", c, "GLOBAL", k, _share(k["fatt"], tot["fatt"]))

        # GLOBAL_BRAND — brand totale
        for b, k in g_gb.iterrows():
            _row("GLOBAL_BRAND", "GLOBAL", "GLOBAL", b, k, _share(k["fatt"], tot["fatt"]))

        # GLOBAL — totale azienda
        _row("GLOBAL", "GLOBAL", "GLOBAL", "GLOBAL", tot, _share(tot["fatt"], tot["fatt"]))

    if not rows:
        return pd.DataFrame(columns=cols)

    # Var % anno su anno — ciascun periodo confronta con il precedente (i periodi sono in
    # ordine [corrente, -1 anno, -2 anni]: il periodo i confronta con il periodo i+1), sulla
    # riga dello stesso scope e della stessa combinazione. Se l'anno prima la combinazione
    # non esisteva la Var % resta vuota (NaN): la convenzione var_pct (+100% da zero) vale
    # solo quando la riga dell'anno prima esiste ed è a zero.
    labels = [lab for lab, _ in periodi]
    pos = {lab: i for i, lab in enumerate(labels)}
    by_key: dict[tuple, dict[str, tuple]] = {}
    for r in rows:
        by_key.setdefault((r["Marketplace"], r["Nazione"], r["Brand"], r["Scope"]), {})[r["Anno"]] = (
            r["Fatturato Netto"], r["Ordini"])
    for r in rows:
        i = pos.get(r["Anno"], -1)
        if i < 0 or i + 1 >= len(labels):
            continue
        prev = by_key[(r["Marketplace"], r["Nazione"], r["Brand"], r["Scope"])].get(labels[i + 1])
        if prev is None:
            continue
        r["Var % Fatturato YoY"] = var_pct(r["Fatturato Netto"], prev[0])
        r["Var % Ordini YoY"] = var_pct(r["Ordini"], prev[1])

    out = pd.DataFrame(rows, columns=cols)
    anno_order = {label: i for i, (label, _) in enumerate(periodi)}
    scope_order = {s: i for i, s in enumerate(
        ["DETAIL", "MARKETPLACE_COUNTRY", "MARKETPLACE_BRAND", "COUNTRY_BRAND",
         "GLOBAL_MARKETPLACE", "GLOBAL_COUNTRY", "GLOBAL_BRAND", "GLOBAL"])}
    out["_anno_ord"] = out["Anno"].map(anno_order)
    out["_scope_ord"] = out["Scope"].map(scope_order)
    out = out.sort_values(["_anno_ord", "_scope_ord", "Fatturato Netto"],
                          ascending=[True, True, False], kind="mergesort")
    return out.drop(columns=["_anno_ord", "_scope_ord"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Log riconciliazione — porting di generateLogRiconciliazioneModulo
# --------------------------------------------------------------------------------------

def log_df(rows: list[dict], cols_map: dict) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(cols_map.values()))
    df = pd.DataFrame(rows)
    df = df.rename(columns=cols_map)
    return df[[c for c in cols_map.values() if c in df.columns]]
