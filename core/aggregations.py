"""
Strumenti di aggregazione — porting di aggregateByKey, aggregateHierarchicalCustom,
aggregateByTagliaPerBrand, filterCarryoverData, getISOWeekKey (helpers.gs).
"""

from __future__ import annotations

import pandas as pd


def aggregate_by_key(df: pd.DataFrame, key_col: str, resi_fp_df: pd.DataFrame | None = None) -> dict:
    """
    Ritorna {"map": {chiave: {ordini, clzMappata, clzOriginale, img, paiaSpedite, paiaRese,
    paiaNette, fatturatoSpedito, fatturatoReso, fatturatoNetto}}, "total": somma nettoNetto}.
    Righe con chiave vuota vengono escluse dalla mappa e dal totale.
    Se `resi_fp_df` è fornito, incorpora i resi fuori periodo per garantire la
    piena quadratura al centesimo con il Fatturato e il conteggio reale delle paia rese.
    """
    result_map = {}
    total = 0.0

    if df is not None and not df.empty and key_col in df.columns:
        work = df.copy()
        work["_key"] = work[key_col].astype(str).str.strip()
        work = work[work["_key"] != ""]

        total += float(work["nettoNetto"].sum())

        grp = work.groupby("_key", sort=False)
        agg = grp.agg(
            paiaSpedite=("paiaSpedite", "sum"),
            paiaRese=("paiaRese", "sum"),
            paiaNette=("paiaNette", "sum"),
            fatturatoSpedito=("nettoSpedito", "sum"),
            fatturatoReso=("nettoReso", "sum"),
            fatturatoNetto=("nettoNetto", "sum"),
            ordini=("ordineId", lambda s: s[s != ""].nunique()),
            clzMappata=("clzMappata", "first") if "clzMappata" in work.columns else ("_key", "first"),
            clzOriginale=("clzOriginale", "first") if "clzOriginale" in work.columns else ("_key", "first"),
            sku13=("sku13", "first") if "sku13" in work.columns else ("_key", "first"),
        )

        for key, r in agg.iterrows():
            result_map[key] = {
                "ordini": int(r["ordini"]),
                "clzMappata": r["clzMappata"], "clzOriginale": r["clzOriginale"],
                "img": str(r["sku13"]).lower() if r["sku13"] else "",
                "paiaSpedite": float(r["paiaSpedite"]), "paiaRese": float(r["paiaRese"]),
                "paiaNette": float(r["paiaNette"]),
                "fatturatoSpedito": float(r["fatturatoSpedito"]), "fatturatoReso": float(r["fatturatoReso"]),
                "fatturatoNetto": float(r["fatturatoNetto"]),
            }

    if resi_fp_df is not None and not resi_fp_df.empty and key_col in resi_fp_df.columns:
        sw = resi_fp_df.copy()
        sw["_key"] = sw[key_col].astype(str).str.strip()
        sw = sw[sw["_key"] != ""]

        total += float(sw["nettoNetto"].sum())

        grp_st = sw.groupby("_key", sort=False).agg(
            paiaRese=("paiaRese", "sum"),
            paiaNette=("paiaNette", "sum"),
            fatturatoReso=("nettoReso", "sum"),
            fatturatoNetto=("nettoNetto", "sum"),
            clzMappata=("clzMappata", "first") if "clzMappata" in sw.columns else ("_key", "first"),
            clzOriginale=("clzOriginale", "first") if "clzOriginale" in sw.columns else ("_key", "first"),
            sku13=("sku13", "first") if "sku13" in sw.columns else ("_key", "first"),
        )

        for key, r in grp_st.iterrows():
            if key in result_map:
                entry = result_map[key]
                entry["paiaRese"] += float(r["paiaRese"])
                entry["paiaNette"] += float(r["paiaNette"])
                entry["fatturatoReso"] += float(r["fatturatoReso"])
                entry["fatturatoNetto"] += float(r["fatturatoNetto"])
            else:
                result_map[key] = {
                    "ordini": 0,
                    "clzMappata": r["clzMappata"], "clzOriginale": r["clzOriginale"],
                    "img": str(r["sku13"]).lower() if r["sku13"] else "",
                    "paiaSpedite": 0.0, "paiaRese": float(r["paiaRese"]),
                    "paiaNette": float(r["paiaNette"]),
                    "fatturatoSpedito": 0.0, "fatturatoReso": float(r["fatturatoReso"]),
                    "fatturatoNetto": float(r["fatturatoNetto"]),
                }

    for entry in result_map.values():
        entry["paiaNette"] = max(0.0, entry["paiaNette"])      # paia nette mai negative (solo resi fuori periodo)
    return {"map": result_map, "total": total}


def aggregate_by_taglia_per_brand(df: pd.DataFrame, resi_fp_df: pd.DataFrame | None = None) -> dict:
    """{ brand: { sottoGruppo: { taglia: {paiaNette, paiaSpedite, paiaRese, fatturatoNetto} } } }"""
    result: dict = {}
    if (df is None or df.empty) and (resi_fp_df is None or resi_fp_df.empty):
        return result

    generi_ok = {"UOMO", "DONNA", "UNISEX", "BAMBINO", "BAMBINA", "ACCESSORI", "ABBIGLIAMENTO"}

    def _process_slice(d_in: pd.DataFrame, is_resi_fp: bool):
        if d_in is None or d_in.empty:
            return
        work = d_in.copy()
        work["_brand"] = work["clzMappata"].astype(str).replace("", "ALTRO").fillna("ALTRO")
        genere_str = work["genere"].astype(str) if "genere" in work.columns else pd.Series("ND", index=work.index)
        work["_gruppo"] = genere_str.where(genere_str.isin(generi_ok), "NON CLASSIFICATO")
        taglia_s = work["taglia"].astype(str) if "taglia" in work.columns else pd.Series("ND", index=work.index)
        work["_taglia"] = taglia_s.replace("", "ND").fillna("ND")

        grp = work.groupby(["_brand", "_gruppo", "_taglia"], sort=False).agg(
            paiaNette=("paiaNette", "sum"), paiaSpedite=("paiaSpedite", "sum"),
            paiaRese=("paiaRese", "sum"), fatturatoNetto=("nettoNetto", "sum"),
        )

        for (brand, gruppo, taglia), r in grp.iterrows():
            target = result.setdefault(brand, {}).setdefault(gruppo, {}).setdefault(taglia, {
                "paiaNette": 0.0, "paiaSpedite": 0.0, "paiaRese": 0.0, "fatturatoNetto": 0.0,
            })
            target["paiaNette"] += float(r["paiaNette"])
            target["paiaSpedite"] += float(r["paiaSpedite"])
            target["paiaRese"] += float(r["paiaRese"])
            target["fatturatoNetto"] += float(r["fatturatoNetto"])

    _process_slice(df, is_resi_fp=False)
    _process_slice(resi_fp_df, is_resi_fp=True)
    for gruppi in result.values():
        for taglie in gruppi.values():
            for d in taglie.values():
                d["paiaNette"] = max(0.0, d["paiaNette"])      # paia nette mai negative
    return result


def aggregate_hierarchical_custom(df: pd.DataFrame, keys: list[str], skip_condition=None,
                                  resi_fp_df: pd.DataFrame | None = None) -> dict:
    """
    Alberatura ricorsiva { tree: {...}, total: somma nettoNetto }. Ogni nodo:
    {paiaSpedite, paiaRese, paiaNette, fatturatoNetto, kids: {...}}.
    `skip_condition(key_name, row)` -> bool: se True, salta quel livello e tutti i successivi
    per quella riga.
    Se `resi_fp_df` è presente, include i resi fuori periodo ad ogni livello.
    """
    tree: dict = {}
    total = 0.0
    if (df is None or df.empty) and (resi_fp_df is None or resi_fp_df.empty):
        return {"tree": tree, "total": total}

    def _traverse_df(data_in: pd.DataFrame):
        nonlocal total
        if data_in is None or data_in.empty:
            return
        for row in data_in.to_dict("records"):
            current = tree
            skip_remaining = False
            for key_name in keys:
                if skip_remaining:
                    break
                if skip_condition and skip_condition(key_name, row):
                    skip_remaining = True
                    break
                k_value = str(row.get(key_name) or "ALTRO").strip()
                if not k_value:
                    k_value = "ALTRO"
                node = current.setdefault(k_value, {
                    "paiaSpedite": 0.0, "paiaRese": 0.0, "paiaNette": 0.0, "fatturatoNetto": 0.0, "kids": {},
                })
                node["paiaSpedite"] += float(row.get("paiaSpedite", 0.0))
                node["paiaRese"] += float(row.get("paiaRese", 0.0))
                node["paiaNette"] += float(row.get("paiaNette", 0.0))
                node["fatturatoNetto"] += float(row.get("nettoNetto", 0.0))
                current = node["kids"]
            total += float(row.get("nettoNetto", 0.0))

    _traverse_df(df)
    _traverse_df(resi_fp_df)

    def _non_negative(nodi: dict) -> None:
        for n in nodi.values():
            n["paiaNette"] = max(0.0, n["paiaNette"])          # paia nette mai negative
            _non_negative(n["kids"])

    _non_negative(tree)
    return {"tree": tree, "total": total}


def filter_carryover_data(current_data: pd.DataFrame, old_data: pd.DataFrame,
                          resi_fp_current: pd.DataFrame | None = None,
                          resi_fp_old: pd.DataFrame | None = None) -> dict:
    """Righe di current/old i cui sku13 sono presenti in ENTRAMBI i dataset ("carryover")."""
    if current_data.empty or old_data.empty:
        return {
            "curr": current_data.iloc[0:0], "old": old_data.iloc[0:0],
            "resi_fp_curr": resi_fp_current.iloc[0:0] if resi_fp_current is not None else pd.DataFrame(),
            "resi_fp_old": resi_fp_old.iloc[0:0] if resi_fp_old is not None else pd.DataFrame(),
        }
    old_skus = set(old_data["sku13"])
    curr_co = current_data[current_data["sku13"].isin(old_skus)]
    curr_skus = set(curr_co["sku13"])
    old_co = old_data[old_data["sku13"].isin(curr_skus)]

    st_c = resi_fp_current[resi_fp_current["sku13"].isin(curr_skus)] if (resi_fp_current is not None and not resi_fp_current.empty) else pd.DataFrame()
    st_o = resi_fp_old[resi_fp_old["sku13"].isin(curr_skus)] if (resi_fp_old is not None and not resi_fp_old.empty) else pd.DataFrame()

    return {"curr": curr_co, "old": old_co, "resi_fp_curr": st_c, "resi_fp_old": st_o}


def get_iso_week_key(date) -> str:
    """Chiave settimana ISO 'YYYY-WW', porting di getISOWeekKey (helpers.gs)."""
    iso = date.isocalendar()
    return f"{iso[0]}-{iso[1]:02d}"
