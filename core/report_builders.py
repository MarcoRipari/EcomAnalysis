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
from . import metrics as met

def var_pct(curr: float, old: float) -> float:
    """Variazione relativa (curr - old) / |old|. Con base zero non è calcolabile: NaN (le tabelle
    mostrano "—" invece di un 100% o 0% inventato)."""
    if old == 0 or old != old or curr != curr:
        return float("nan")
    return (curr - old) / abs(old)


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
    if kc["paiaSped"] == 0 and ko["paiaSped"] == 0 and kc["fattReale"] == 0 and ko["fattReale"] == 0:
        return None
    rows = [
        ("FATTURATO", kc["fattReale"], ko["fattReale"], "currency"),
        ("PAIA NETTE VENDUTE", kc["paiaNette"], ko["paiaNette"], "number"),
        ("VALORE MEDIO PAIO", kc["valMedio"], ko["valMedio"], "currency"),
        ("SCONTRINO MEDIO", kc["scontrinoMedio"], ko["scontrinoMedio"], "currency"),
        ("% RESO", kc["percReso"], ko["percReso"], "percent"),
    ]
    # la variazione di una percentuale è la differenza in punti (22% → 24% = +2,0 pp), non il +9% relativo
    data = [(m, fmt.fmt(c, k), fmt.fmt(o, k),
             fmt.fmt_pp(c - o) if k == "percent" else fmt.fmt_var(var_pct(c, o))) for m, c, o, k in rows]
    return pd.DataFrame(data, columns=["Metrica", str(y_curr), str(y_old), "Var % Y2Y"])


# --------------------------------------------------------------------------------------
# Tabella comparativa Y2Y — porting di drawComparativeTable
# --------------------------------------------------------------------------------------

def comparative_table(agg_current: dict, agg_old: dict, y_curr: int, y_old: int,
                       sort_type: str = "fatturatoNetto") -> pd.DataFrame:
    all_keys = set(agg_current["map"].keys()) | set(agg_old["map"].keys())
    empty = {"ordini": 0, "paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0,
             "fatturatoSpedito": 0.0, "fatturatoNetto": 0.0}

    def scontrino(d):
        return d["fatturatoSpedito"] / d["ordini"] if d["ordini"] > 0 else 0.0

    rows = []
    for key in all_keys:
        c = agg_current["map"].get(key, empty)
        o = agg_old["map"].get(key, empty)
        var_fatt = var_pct(c["fatturatoNetto"], o["fatturatoNetto"])
        p_reso_c = c["paiaRese"] / c["paiaSpedite"] if c["paiaSpedite"] > 0 else 0.0
        rows.append([key, c["fatturatoNetto"], o["fatturatoNetto"], var_fatt,
                     c["paiaNette"], o["paiaNette"], scontrino(c), scontrino(o), p_reso_c,
                     c.get(sort_type, 0)])

    cols = ["Chiave", f"Fatturato {y_curr}", f"Fatturato {y_old}", "VAR% FATT",
            f"Paia Nette {y_curr}", f"Paia Nette {y_old}",
            f"Scontrino Medio {y_curr}", f"Scontrino Medio {y_old}", f"% Reso {y_curr}", "_sort"]
    df = pd.DataFrame(rows, columns=cols).sort_values("_sort", ascending=False).drop(columns="_sort")
    return df.reset_index(drop=True)


def single_year_table(aggregator: dict, y_curr: int, sort_type: str = "fatturatoNetto") -> pd.DataFrame:
    """Porting di drawSingleYearTable (usato nella Dashboard, un solo anno)."""
    rows = []
    for key, c in aggregator["map"].items():
        p_reso = c["paiaRese"] / c["paiaSpedite"] if c["paiaSpedite"] > 0 else 0.0
        val_medio = c["fatturatoNetto"] / c["paiaNette"] if c["paiaNette"] > 0 else 0.0
        scontrino = c["fatturatoSpedito"] / c["ordini"] if c["ordini"] > 0 else 0.0
        rows.append([key, c["paiaSpedite"], c["paiaRese"], p_reso,
                     c["paiaNette"], val_medio, scontrino, c["fatturatoNetto"], c.get(sort_type, 0)])
    cols = ["Chiave", "Paia Spedite", "Paia Rese", "% Reso", "Paia Nette",
            "Valore Medio Paio", "Scontrino Medio", f"Fatturato {y_curr}", "_sort"]
    df = pd.DataFrame(rows, columns=cols).sort_values("_sort", ascending=False).drop(columns="_sort")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Top articoli — porting di drawTopArticoliY2Y (con confronto Y2Y) e della sezione
# "TOP ARTICOLI" della Dashboard (solo anno corrente, livello SKU13)
# --------------------------------------------------------------------------------------

def top_articoli_y2y(current_data: pd.DataFrame, old_data: pd.DataFrame, anagrafica: dict,
                      y_curr: int, y_old: int, top_n: int = 20,
                      resi_fp_current: pd.DataFrame | None = None,
                      resi_fp_old: pd.DataFrame | None = None) -> pd.DataFrame:
    has_old = old_data is not None and not old_data.empty

    def build(df, is_current, m, is_resi_fp=False):
        if df is None or df.empty:
            return
        g = df.groupby("sku7", sort=False).agg(
            pCNet=("paiaNette", "sum"), pCSped=("paiaSpedite", "sum"),
            pCRes=("paiaRese", "sum"), f=("nettoNetto", "sum"),
            clz=("clzOriginale", "first") if "clzOriginale" in df.columns else ("sku7", "first"),
            sku13=("sku13", "first") if "sku13" in df.columns else ("sku7", "first"),
        )
        for cod, r in g.iterrows():
            entry = m.setdefault(cod, {"pCNet": 0.0, "pCSped": 0.0, "pCRes": 0.0, "fC": 0.0, "fO": 0.0,
                                        "clz": r["clz"], "img": str(r["sku13"]).lower() if r["sku13"] else ""})
            if is_current:
                entry["pCNet"] += float(r["pCNet"])
                entry["pCSped"] += float(r["pCSped"])
                entry["pCRes"] += float(r["pCRes"])
                entry["fC"] += float(r["f"])
            else:
                entry["fO"] += float(r["f"])

    map_data: dict = {}
    build(current_data, True, map_data)
    build(resi_fp_current, True, map_data, is_resi_fp=True)
    if has_old:
        build(old_data, False, map_data)
        build(resi_fp_old, False, map_data, is_resi_fp=True)

    rows = []
    for cod, d in map_data.items():
        desc = anagrafica.get(cod, {}).get("desc", "-")
        p_reso_c = d["pCRes"] / d["pCSped"] if d["pCSped"] > 0 else 0.0
        var_fatt = var_pct(d["fC"], d["fO"]) if has_old else None
        row = {"Foto": img_url(d["img"]), "Codice": cod, "Descrizione": desc,
               f"Paia Nette {y_curr}": max(0.0, d["pCNet"]), f"Fatturato {y_curr}": d["fC"]}
        if has_old:
            row[f"Fatturato {y_old}"] = d["fO"]
            row["VAR% FATT"] = var_fatt
        row[f"% Reso {y_curr}"] = p_reso_c
        row["_sort"] = d["fC"]
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("_sort", ascending=False).drop(columns="_sort").head(top_n).reset_index(drop=True)


def top_articoli_dashboard(current_data: pd.DataFrame, anagrafica: dict, top_n: int = 5000,
                           resi_fp_data: pd.DataFrame | None = None) -> pd.DataFrame:
    """Porting della tabella Top Articoli della Dashboard (livello SKU13, solo anno corrente)."""
    agg_sku = agg.aggregate_by_key(current_data, "sku13", resi_fp_data)
    rows = []
    for sku, item in agg_sku["map"].items():
        desc = anagrafica.get(sku, {}).get("desc") or anagrafica.get(sku[:7], {}).get("desc", "-")
        p_reso = item["paiaRese"] / item["paiaSpedite"] if item["paiaSpedite"] > 0 else 0.0
        rows.append({
            "Foto": img_url(item["img"]), "Articolo": f"{sku.upper()} — {desc}",
            "Collezione": item["clzOriginale"], "Paia Spedite": item["paiaSpedite"],
            "Paia Rese": item["paiaRese"], "% Reso": p_reso, "Paia Nette": item["paiaNette"],
            "Valore Reso": item["fatturatoReso"], "Fatturato": item["fatturatoNetto"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("Fatturato", ascending=False).head(top_n).reset_index(drop=True)


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


def _stats_mensili(venduto: pd.DataFrame, resi_fp: pd.DataFrame | None,
                   mesi: list[tuple[int, int]]) -> dict[tuple[int, int], dict]:
    """(anno, mese) → metriche del mese.
    Le vendite sono attribuite al mese di dataVendita; tutti i resi (sia del venduto con
    dataReso nel periodo, sia fuori periodo) sono attribuiti al mese di dataReso.
    In questo modo le metriche mensili della tabella Y2Y coincidono perfettamente con
    quelle calcolate analizzando il singolo mese in Dashboard."""
    stats = {ym: {"fatturato": 0.0, "paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0,
                  "nettoSpedito": 0.0, "nettoReso": 0.0, "ordini": 0} for ym in mesi}

    v = venduto
    if v is not None and not v.empty and "dataVendita" in v.columns:
        v_sales = v[v["dataVendita"].notna()].copy()
        if not v_sales.empty:
            v_sales["_ym"] = list(zip(v_sales["dataVendita"].dt.year.astype(int),
                                      v_sales["dataVendita"].dt.month.astype(int)))
            v_sales["_ord"] = v_sales["ordineId"].where(v_sales["ordineId"] != "")
            g_sales = v_sales.groupby("_ym").agg({
                "nettoSpedito": "sum", "paiaSpedite": "sum", "_ord": "nunique",
            })
            for ym, r in g_sales.iterrows():
                if ym in stats:
                    stats[ym]["nettoSpedito"] += float(r["nettoSpedito"])
                    stats[ym]["paiaSpedite"] += float(r["paiaSpedite"])
                    stats[ym]["ordini"] = int(r["_ord"])

    # Resi del venduto: attribuiti al mese del reso (se reso effettivo nel periodo)
    if v is not None and not v.empty and "dataReso" in v.columns:
        v_resi = v[v["isReso"] & v["dataReso"].notna()].copy()
        if not v_resi.empty:
            v_resi["_ym"] = list(zip(v_resi["dataReso"].dt.year.astype(int),
                                     v_resi["dataReso"].dt.month.astype(int)))
            g_vr = v_resi.groupby("_ym").agg({"nettoReso": "sum", "paiaRese": "sum"})
            for ym, r in g_vr.iterrows():
                if ym in stats:
                    stats[ym]["nettoReso"] += float(r["nettoReso"])
                    stats[ym]["paiaRese"] += float(r["paiaRese"])

    # Resi fuori periodo: attribuiti al mese del reso
    s = resi_fp
    if s is not None and not s.empty and "dataReso" in s.columns:
        s = s.copy()
        d = pd.to_datetime(s["dataReso"].fillna(s.get("dataVendita")))
        s["_ym"] = list(zip(d.dt.year.astype(int), d.dt.month.astype(int)))
        g_s = s.groupby("_ym").agg({"nettoReso": "sum", "paiaRese": "sum"})
        for ym, r in g_s.iterrows():
            if ym in stats:
                stats[ym]["nettoReso"] += float(r["nettoReso"])
                stats[ym]["paiaRese"] += float(r["paiaRese"])

    for st in stats.values():
        st["fatturato"] = st["nettoSpedito"] - st["nettoReso"]
        st["paiaNette"] = max(0.0, st["paiaSpedite"] - st["paiaRese"])               # mai negative
        st["percReso"] = st["paiaRese"] / st["paiaSpedite"] if st["paiaSpedite"] > 0 else 0.0
        st["scontrino"] = st["nettoSpedito"] / st["ordini"] if st["ordini"] > 0 else 0.0
    return stats


def _agg_stagioni(stats: dict[tuple[int, int], dict]) -> dict[str, dict]:
    """Somma le statistiche mensili per stagione (etichetta 'SS 2026' / 'FW 25/26'),
    mantenendo l'ordine cronologico di prima comparsa."""
    stagioni: dict[str, dict] = {}
    for (y, m), st in stats.items():
        lab = _stagione_label(y, m)
        d = stagioni.setdefault(lab, {"fatturato": 0.0, "paiaSpedite": 0.0, "paiaRese": 0.0,
                                      "paiaNette": 0.0, "nettoSpedito": 0.0, "ordini": 0, "mesi": 0})
        for k in ("fatturato", "paiaSpedite", "paiaRese", "paiaNette", "nettoSpedito", "ordini"):
            d[k] += st[k]
        d["mesi"] += 1
    for d in stagioni.values():
        d["percReso"] = d["paiaRese"] / d["paiaSpedite"] if d["paiaSpedite"] > 0 else 0.0
        d["scontrino"] = d["nettoSpedito"] / d["ordini"] if d["ordini"] > 0 else 0.0
    return stagioni


def monthly_season_report(da, a,
                           periodi: list[tuple[str, pd.DataFrame, pd.DataFrame]]
                           ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Report "Mese per Mese" con stagioni SS/FW, a finestra mobile sul periodo scelto.

    `periodi` = [(etichetta, venduto, resi fuori periodo), …]: la posizione i corrisponde
    al periodo scelto spostato di −i anni (0 = periodo scelto, 1 = anno−1, 2 = anno−2),
    quindi ogni riga-mese confronta lo stesso mese degli anni precedenti (con confronti=0
    la tabella mostra solo il periodo scelto, senza colonne di variazione).

    Ritorna (df_mesi, df_stagioni):
      df_mesi   — una riga per ogni mese da month(da) a month(a), con: Fatturato,
                  Paia Nette e % Reso del periodo corrente; per ogni anno di
                  confronto: Fatturato e VAR% di fatturato/paia;
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
        riga[f"Fatturato {labels[0]}"] = cur["fatturato"]
        riga[f"Paia Nette {labels[0]}"] = cur["paiaNette"]
        riga[f"% Reso {labels[0]}"] = cur["percReso"]
        riga[f"Scontrino Medio {labels[0]}"] = cur["scontrino"]
        for i in range(1, len(periodi)):
            old = stats[i].get((y - i, m))
            riga[f"Fatturato {labels[i]}"] = old["fatturato"]
            riga[f"VAR% FATT vs {labels[i]}"] = var_pct(cur["fatturato"], old["fatturato"])
            riga[f"VAR% PAIA vs {labels[i]}"] = var_pct(cur["paiaNette"], old["paiaNette"])
            riga[f"Scontrino Medio {labels[i]}"] = old["scontrino"]
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
        riga[f"Fatturato {labels[0]}"] = cur["fatturato"]
        riga[f"Paia Nette {labels[0]}"] = cur["paiaNette"]
        riga[f"% Reso {labels[0]}"] = cur["percReso"]
        riga[f"Scontrino Medio {labels[0]}"] = cur["scontrino"]
        for i in range(1, len(periodi)):
            old = stag[i].get(ordini[i][k]) if k < len(ordini[i]) else None
            if old is None:
                continue
            riga[f"Fatturato {labels[i]}"] = old["fatturato"]
            riga[f"VAR% FATT vs {labels[i]}"] = var_pct(cur["fatturato"], old["fatturato"])
            riga[f"VAR% PAIA vs {labels[i]}"] = var_pct(cur["paiaNette"], old["paiaNette"])
            riga[f"Scontrino Medio {labels[i]}"] = old["scontrino"]
        righe.append(riga)
    df_stagioni = pd.DataFrame(righe)
    return df_mesi, df_stagioni


# --------------------------------------------------------------------------------------
# Comparativa Codici (SKU7) — porting di generateComparativaCodiciModulo
# --------------------------------------------------------------------------------------

def comparativa_codici(current_data: pd.DataFrame, old_data: pd.DataFrame, anagrafica: dict,
                        y_curr: int, y_old: int,
                        resi_fp_current: pd.DataFrame | None = None,
                        resi_fp_old: pd.DataFrame | None = None) -> pd.DataFrame:
    map_data: dict = {}

    def build(df, is_current, is_resi_fp=False):
        if df is None or df.empty:
            return
        g = df.groupby("sku7", sort=False).agg(
            pNet=("paiaNette", "sum"), pSped=("paiaSpedite", "sum"), pRes=("paiaRese", "sum"),
            f=("nettoNetto", "sum"),
            clz=("clzOriginale", "first") if "clzOriginale" in df.columns else ("sku7", "first"),
            sku13=("sku13", "first") if "sku13" in df.columns else ("sku7", "first"),
        )
        for cod, r in g.iterrows():
            e = map_data.setdefault(cod, {"pCNet": 0.0, "pCSped": 0.0, "pCRes": 0.0, "fC": 0.0,
                                           "pONet": 0.0, "pOSped": 0.0, "pORes": 0.0, "fO": 0.0,
                                           "clz": r["clz"], "img": str(r["sku13"]).lower() if r["sku13"] else ""})
            if is_current:
                e["pCNet"] += float(r["pNet"])
                e["pCSped"] += float(r["pSped"])
                e["pCRes"] += float(r["pRes"])
                e["fC"] += float(r["f"])
            else:
                e["pONet"] += float(r["pNet"])
                e["pOSped"] += float(r["pSped"])
                e["pORes"] += float(r["pRes"])
                e["fO"] += float(r["f"])

    build(current_data, True)
    build(resi_fp_current, True, is_resi_fp=True)
    build(old_data, False)
    build(resi_fp_old, False, is_resi_fp=True)

    rows = []
    for cod, d in map_data.items():
        desc = anagrafica.get(cod, {}).get("desc", "-")
        var_fatt = var_pct(d["fC"], d["fO"])
        p_reso_c = d["pCRes"] / d["pCSped"] if d["pCSped"] > 0 else 0.0
        p_reso_o = d["pORes"] / d["pOSped"] if d["pOSped"] > 0 else 0.0
        rows.append([img_url(d["img"]), cod, d["clz"], desc, max(0.0, d["pCNet"]), p_reso_c, d["fC"],
                     max(0.0, d["pONet"]), p_reso_o, d["fO"], var_fatt])

    cols = ["Foto", "Codice", "Collezione", "Descrizione", f"Paia Net {y_curr}", f"% Reso {y_curr}",
            f"Fatturato {y_curr}", f"Paia Net {y_old}", f"% Reso {y_old}", f"Fatturato {y_old}", "VAR% FATT"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    return df.sort_values(f"Fatturato {y_curr}", ascending=False).reset_index(drop=True)


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
            v_f = var_pct(c_node["fatturatoNetto"], o_node["fatturatoNetto"])
            v_p = var_pct(c_node["paiaNette"], o_node["paiaNette"])
            p_reso_c = c_node["paiaRese"] / c_node["paiaSpedite"] if c_node["paiaSpedite"] > 0 else 0.0
            p_reso_o = o_node["paiaRese"] / o_node["paiaSpedite"] if o_node["paiaSpedite"] > 0 else 0.0

            indent = "\u2003\u2003" * depth
            label = indent + ("📁 " if depth == 0 else "🏷️ ") + (key.upper() if depth == 0 else key)

            rows.append({
                "Voce": label, "Depth": depth,
                "Paia Net Curr": c_node["paiaNette"], "% Reso Curr": p_reso_c,
                "Fatturato Curr": c_node["fatturatoNetto"], "% Tot Curr": p_c,
                "Paia Net Old": o_node["paiaNette"], "% Reso Old": p_reso_o,
                "Fatturato Old": o_node["fatturatoNetto"], "% Tot Old": p_o,
                "VAR% FATT": v_f, "VAR% PAIA": v_p,
            })
            if depth < max_depth - 1:
                traverse(c_node["kids"], o_node["kids"], depth + 1)

    traverse(current_tree["tree"], old_tree["tree"], 0)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Analisi Resi (status per collezione) — porting di generateResiModulo
# --------------------------------------------------------------------------------------

def resi_status(current_data: pd.DataFrame, resi_fp_current: pd.DataFrame | None = None) -> pd.DataFrame:
    agg_data = agg.aggregate_by_key(current_data, "clzMappata", resi_fp_current)
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
                                      "Fatturato", "Status"])
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


def taglie_tables(current_data: pd.DataFrame, resi_fp_current: pd.DataFrame | None = None) -> dict:
    """{ brand: { gruppo: DataFrame[Taglia, Paia Nette, % su gruppo, % Reso, Fatturato] } }"""
    by_brand = agg.aggregate_by_taglia_per_brand(current_data, resi_fp_current)
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
                rows, columns=["Taglia", "Paia Nette", f"% su {gruppo}", "% Reso", "Fatturato"])
    return result


# --------------------------------------------------------------------------------------
# Comparativa Nazioni — nuova pagina "Nazioni"
# --------------------------------------------------------------------------------------

def nazioni_disponibili(*dfs: pd.DataFrame) -> list[str]:
    naz = set()
    for df in dfs:
        if df is not None and not df.empty and "nazione" in df.columns:
            naz |= set(df["nazione"].astype(str).unique())
    return sorted(naz)


def _per_nazione(df: pd.DataFrame | None, nazione: str) -> pd.DataFrame | None:
    if df is None or df.empty or nazione == "GLOBAL":
        return df
    return df[df["nazione"].astype(str) == nazione]


def nazioni_metrics(venduto: pd.DataFrame, resi_fp: pd.DataFrame, nazioni: list[str]) -> pd.DataFrame:
    """Una riga per nazione selezionata (GLOBAL = tutte), con gli stessi KPI di metrics.kpi_reali."""
    rows = []
    for naz in nazioni:
        k = met.kpi_reali(_per_nazione(venduto, naz), _per_nazione(resi_fp, naz))
        rows.append([naz, k["fattReale"], k["paiaNette"], k["paiaResePeriodo"],
                     k["paiaReseFuoriPeriodo"], k["percReso"]])
    cols = ["Nazione", "Fatturato", "Paia Nette", "Paia Rese (vendite del periodo)",
            "Paia Rese (vendite fuori periodo)", "% Reso"]
    return pd.DataFrame(rows, columns=cols)


def nazioni_brand_share(venduto: pd.DataFrame, nazione: str, resi_fp: pd.DataFrame | None = None) -> pd.DataFrame:
    """Share % del Fatturato per brand (clzMappata), per una singola nazione."""
    cols = ["Brand", "Fatturato", "Share %", "Valore Medio Paio",
            "Paia spedite", "Paia rese", "Paia nette", "% Reso"]
    pezzi = [d for d in (_per_nazione(venduto, nazione), _per_nazione(resi_fp, nazione))
             if d is not None and not d.empty]
    if not pezzi:
        return pd.DataFrame(columns=cols)

    work = pd.concat(pezzi, ignore_index=True)
    work["_brand"] = work["clzMappata"].astype(str).replace("", "ALTRO")
    g = work.groupby("_brand", sort=False, observed=True).agg(
        **{"Fatturato": ("nettoNetto", "sum"), "Paia spedite": ("paiaSpedite", "sum"),
           "Paia rese": ("paiaRese", "sum"), "Paia nette": ("paiaNette", "sum")}
    ).reset_index().rename(columns={"_brand": "Brand"})

    g["Paia nette"] = g["Paia nette"].clip(lower=0)                 # mai negative
    tot = float(g["Fatturato"].sum())
    g["Share %"] = g["Fatturato"] / tot if tot != 0 else 0.0
    g["% Reso"] = np.where(g["Paia spedite"] > 0, g["Paia rese"] / g["Paia spedite"], 0.0)
    g["Valore Medio Paio"] = np.where(g["Paia nette"] > 0, g["Fatturato"] / g["Paia nette"], 0.0)
    return g[cols].sort_values("Fatturato", ascending=False).reset_index(drop=True)
