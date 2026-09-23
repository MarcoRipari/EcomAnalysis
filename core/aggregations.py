"""
Strumenti di aggregazione — porting di aggregateByKey, aggregateHierarchicalCustom,
aggregateByTagliaPerBrand, filterCarryoverData, getISOWeekKey (helpers.gs).
"""

from __future__ import annotations

import pandas as pd


def aggregate_by_key(df: pd.DataFrame, key_col: str) -> dict:
    """
    Ritorna {"map": {chiave: {ordini, clzMappata, clzOriginale, img, paiaSpedite, paiaRese,
    paiaNette, fatturatoSpedito, fatturatoReso, fatturatoNetto}}, "total": somma nettoNetto}.
    Righe con chiave vuota vengono escluse dalla mappa (ma contano nel totale, come in JS
    dove il return anticipato salta solo l'aggiornamento della entry ma non il totale... in
    realtà nell'originale il return salta anche il totale: qui replichiamo esattamente,
    escludendo dal totale le righe a chiave vuota).
    """
    if df.empty:
        return {"map": {}, "total": 0.0}

    work = df.copy()
    work["_key"] = work[key_col].astype(str).str.strip()
    work = work[work["_key"] != ""]

    total = float(work["nettoNetto"].sum())

    grp = work.groupby("_key", sort=False)
    agg = grp.agg(
        paiaSpedite=("paiaSpedite", "sum"),
        paiaRese=("paiaRese", "sum"),
        paiaNette=("paiaNette", "sum"),
        fatturatoSpedito=("nettoSpedito", "sum"),
        fatturatoReso=("nettoReso", "sum"),
        fatturatoNetto=("nettoNetto", "sum"),
        ordini=("ordineId", lambda s: s[s != ""].nunique()),
        clzMappata=("clzMappata", "first"),
        clzOriginale=("clzOriginale", "first"),
        sku13=("sku13", "first"),
    )

    result_map = {}
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
    return {"map": result_map, "total": total}


def aggregate_by_taglia_per_brand(df: pd.DataFrame) -> dict:
    """{ brand: { sottoGruppo: { taglia: {paiaNette, paiaSpedite, paiaRese, fatturatoNetto} } } }"""
    result: dict = {}
    if df.empty:
        return result

    work = df.copy()
    work["_brand"] = work["clzMappata"].astype(str).replace("", "ALTRO").fillna("ALTRO")
    generi_ok = {"UOMO", "DONNA", "UNISEX", "BAMBINO", "BAMBINA", "ACCESSORI", "ABBIGLIAMENTO"}
    genere_str = work["genere"].astype(str)
    work["_gruppo"] = genere_str.where(genere_str.isin(generi_ok), "NON CLASSIFICATO")
    work["_taglia"] = work["taglia"].astype(str).replace("", "ND").fillna("ND")

    grp = work.groupby(["_brand", "_gruppo", "_taglia"], sort=False).agg(
        paiaNette=("paiaNette", "sum"), paiaSpedite=("paiaSpedite", "sum"),
        paiaRese=("paiaRese", "sum"), fatturatoNetto=("nettoNetto", "sum"),
    )

    for (brand, gruppo, taglia), r in grp.iterrows():
        result.setdefault(brand, {}).setdefault(gruppo, {})[taglia] = {
            "paiaNette": float(r["paiaNette"]), "paiaSpedite": float(r["paiaSpedite"]),
            "paiaRese": float(r["paiaRese"]), "fatturatoNetto": float(r["fatturatoNetto"]),
        }
    return result


def aggregate_hierarchical_custom(df: pd.DataFrame, keys: list[str], skip_condition=None) -> dict:
    """
    Alberatura ricorsiva { tree: {...}, total: somma nettoNetto }. Ogni nodo:
    {paiaSpedite, paiaRese, paiaNette, fatturatoNetto, kids: {...}}.
    `skip_condition(key_name, row)` -> bool: se True, salta quel livello e tutti i successivi
    per quella riga (porting fedele del comportamento in JS).
    """
    tree: dict = {}
    total = 0.0
    if df.empty:
        return {"tree": tree, "total": total}

    for row in df.to_dict("records"):
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
            node["paiaSpedite"] += row["paiaSpedite"]
            node["paiaRese"] += row["paiaRese"]
            node["paiaNette"] += row["paiaNette"]
            node["fatturatoNetto"] += row["nettoNetto"]
            current = node["kids"]
        total += row["nettoNetto"]

    return {"tree": tree, "total": total}


def filter_carryover_data(current_data: pd.DataFrame, old_data: pd.DataFrame) -> dict:
    """Righe di current/old i cui sku13 sono presenti in ENTRAMBI i dataset ("carryover")."""
    if current_data.empty or old_data.empty:
        return {"curr": current_data.iloc[0:0], "old": old_data.iloc[0:0]}
    old_skus = set(old_data["sku13"])
    curr_co = current_data[current_data["sku13"].isin(old_skus)]
    curr_skus = set(curr_co["sku13"])
    old_co = old_data[old_data["sku13"].isin(curr_skus)]
    return {"curr": curr_co, "old": old_co}


def get_iso_week_key(date) -> str:
    """Chiave settimana ISO 'YYYY-WW', porting di getISOWeekKey (helpers.gs)."""
    iso = date.isocalendar()
    return f"{iso[0]}-{iso[1]:02d}"
