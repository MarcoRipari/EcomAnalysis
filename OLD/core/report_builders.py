"""
Report builders — porting della LOGICA (non della UI a fogli/celle) dei moduli in
reports.gs e tables.gs. Ogni funzione ritorna strutture dati semplici (dict / DataFrame)
pronte per essere renderizzate da una pagina Streamlit con st.dataframe / st.metric /
st.plotly_chart, al posto delle chiamate SpreadsheetApp dell'originale.
"""

from __future__ import annotations

import pandas as pd

from . import aggregations as agg
from . import config as CFG


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
    if kc["ordini"] == 0 and ko["ordini"] == 0:
        return None
    rows = [
        ("FATTURATO NETTO REALE", kc["fattReale"], ko["fattReale"]),
        ("TOTALE ORDINI", kc["ordini"], ko["ordini"]),
        ("PAIA NETTE VENDUTE", kc["paiaNette"], ko["paiaNette"]),
        ("VALORE MEDIO PAIO", kc["valMedio"], ko["valMedio"]),
        ("% RESO", kc["percReso"], ko["percReso"]),
    ]
    data = [(m, c, o, var_pct(c, o)) for m, c, o in rows]
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
# Log riconciliazione — porting di generateLogRiconciliazioneModulo
# --------------------------------------------------------------------------------------

def log_df(rows: list[dict], cols_map: dict) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(cols_map.values()))
    df = pd.DataFrame(rows)
    df = df.rename(columns=cols_map)
    return df[[c for c in cols_map.values() if c in df.columns]]
