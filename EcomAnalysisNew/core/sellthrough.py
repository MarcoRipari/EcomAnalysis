"""
Sell-Through — porting di parseSellInRaw() (backend.gs) e generateSellThroughModulo()
(reports.gs). Il tab BUYING (sell-in) va fornito come CSV a parte, con lo stesso layout
colonne (posizionale) del foglio originale: colonna F (idx5) = codice, G (idx6) = variante,
H (idx7) = colore, L (idx11) = quantità, AV (idx47) = codice cliente.
"""

from __future__ import annotations

import io

import pandas as pd

from . import config as CFG
from . import aggregations as agg
from . import report_builders as rb
from .engine import _to_bytes


BUYING_COLS = {"COD": 5, "VAR": 6, "COL": 7, "QTY": 11, "CLIENTE": 47}


def read_buying_csv(file_or_path) -> pd.DataFrame:
    raw_bytes = _to_bytes(file_or_path)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(
                io.BytesIO(raw_bytes), sep=";", header=None, skiprows=1, dtype=str,
                quotechar='"', engine="c", encoding=enc, on_bad_lines="skip",
                keep_default_na=False,
            )
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("Impossibile leggere il CSV BUYING con nessuno degli encoding tentati.")


def parse_sell_in_raw(df_buying: pd.DataFrame, tipo_buying: str) -> list[dict]:
    """tipo_buying: '1'/'GLOBALE' = tutto, '2' = solo DIRETTI, '3' = solo ESTERNI."""
    c = BUYING_COLS
    n = df_buying.shape[1]
    if n <= max(c.values()):
        raise ValueError(
            f"Il CSV BUYING ha solo {n} colonne, ne servono almeno {max(c.values()) + 1} "
            "(stesso layout della tab BUYING originale)."
        )

    result = []
    for row in df_buying.itertuples(index=False, name=None):
        cod_raw = str(row[c["COD"]]).strip().replace("-", "")
        var_raw = str(row[c["VAR"]]).strip().replace("-", "")
        col_raw = str(row[c["COL"]]).strip().replace("-", "")
        try:
            qty = float(str(row[c["QTY"]]).replace(",", "."))
        except ValueError:
            qty = 0.0
        codice_cliente = str(row[c["CLIENTE"]]).strip()

        if not cod_raw or qty == 0:
            continue

        appartenenza = "ALTRO"
        if codice_cliente in CFG.CODICI_DIRETTI:
            appartenenza = "DIRETTI"
        elif codice_cliente in CFG.CODICI_ESTERNI:
            appartenenza = "ESTERNI"

        if tipo_buying == "2" and appartenenza != "DIRETTI":
            continue
        if tipo_buying == "3" and appartenenza != "ESTERNI":
            continue

        base = cod_raw[3:] if cod_raw.startswith("001") else cod_raw
        sku13 = (base + var_raw + col_raw)[:13].ljust(13, "0")
        result.append({"sku13": sku13, "qty": qty})
    return result


def generate_sell_through(current_data: pd.DataFrame, sell_in_raw: list[dict], anagrafica: dict,
                           lunghezza: int) -> pd.DataFrame:
    if not sell_in_raw:
        return pd.DataFrame()

    sell_in_map: dict[str, float] = {}
    sell_in_sku13: dict[str, str] = {}
    valid_sku13: set[str] = set()

    for item in sell_in_raw:
        valid_sku13.add(item["sku13"])
        chiave = item["sku13"][:lunghezza]
        sell_in_map[chiave] = sell_in_map.get(chiave, 0.0) + item["qty"]
        sell_in_sku13.setdefault(chiave, item["sku13"].lower())

    df = current_data[current_data["sku13"].isin(valid_sku13)].copy()
    if df.empty:
        return pd.DataFrame()

    df["_chiave"] = df["sku13"].str.slice(0, lunghezza)
    df = df[df["_chiave"].isin(sell_in_map.keys())]
    df = df[df["dataVendita"].notna()]

    df["_settimana"] = df["dataVendita"].apply(agg.get_iso_week_key)

    tot_paia_globale = df["paiaNette"].sum()

    data_map: dict[str, dict] = {}
    for chiave, grp in df.groupby("_chiave", sort=False):
        promo_mask = grp["isPromo"]
        totale = grp
        inseason = grp[~promo_mask]
        promo = grp[promo_mask]

        def block(sub):
            return {
                "paiaNette": sub["paiaNette"].sum(),
                "fattNetto": sub["nettoNetto"].sum(),
                "settimane": sub.loc[sub["paiaNette"] > 0, "_settimana"].nunique(),
            }

        data_map[chiave] = {
            "codiceFoto": sell_in_sku13.get(chiave, ""),
            "totale": block(totale), "inseason": block(inseason), "promo": block(promo),
            "dataMin": totale["dataVendita"].min(), "dataMax": totale["dataVendita"].max(),
        }

    rows = []
    for chiave, paia_acq in sell_in_map.items():
        if paia_acq <= 0:
            continue
        d = data_map.get(chiave)
        anag = anagrafica.get(chiave, anagrafica.get(chiave[:7], {"clz": "-", "desc": "-", "serie": "-"}))
        if d is None:
            d = {"codiceFoto": chiave.lower(), "totale": {"paiaNette": 0, "fattNetto": 0, "settimane": 0},
                 "inseason": {"paiaNette": 0, "fattNetto": 0, "settimane": 0},
                 "promo": {"paiaNette": 0, "fattNetto": 0, "settimane": 0}, "dataMin": None, "dataMax": None}

        def metrics_blocco(b):
            vend = b["paiaNette"]
            resid = max(0.0, paia_acq - vend)
            st = min(1.0, vend / paia_acq) if paia_acq > 0 else 0.0
            sett = b["settimane"]
            vel = vend / sett if sett > 0 else 0.0
            p_medio = b["fattNetto"] / vend if vend > 0 else 0.0
            return vend, resid, st, b["fattNetto"], p_medio, vel, sett

        tot_vend, tot_resid, tot_st, tot_fatt, tot_pm, tot_vel, tot_sett = metrics_blocco(d["totale"])
        is_vend, is_resid, is_st, is_fatt, is_pm, is_vel, is_sett = metrics_blocco(d["inseason"])
        pr_vend, pr_resid, pr_st, pr_fatt, pr_pm, pr_vel, pr_sett = metrics_blocco(d["promo"])

        perc_paia_globale = tot_vend / tot_paia_globale if tot_paia_globale > 0 else 0.0

        rows.append({
            "Foto": rb.img_url(d["codiceFoto"]), "Codice": chiave, "Collezione": anag.get("clz", "-"),
            "Serie": anag.get("serie", "-"), "Descrizione": anag.get("desc", "-"),
            "Acq.": paia_acq,
            "Vend. Tot": tot_vend, "Resid. Tot": tot_resid, "ST% Tot": tot_st, "Fatt.Netto Tot": tot_fatt,
            "P.Medio Tot": tot_pm, "Vel/w Tot": tot_vel, "Sett Tot": tot_sett,
            "Vend. In-Season": is_vend, "Resid. In-Season": is_resid, "ST% In-Season": is_st,
            "Fatt.Netto In-Season": is_fatt, "P.Medio In-Season": is_pm, "Vel/w In-Season": is_vel,
            "Sett In-Season": is_sett,
            "Vend. Promo": pr_vend, "Resid. Promo": pr_resid, "ST% Promo": pr_st,
            "Fatt.Netto Promo": pr_fatt, "P.Medio Promo": pr_pm, "Vel/w Promo": pr_vel, "Sett Promo": pr_sett,
            "% su Paia Totali": perc_paia_globale,
            "1° Vendita": d["dataMin"], "Ultima Vendita": d["dataMax"],
            "_sort_paia": tot_vend, "_sort_fatt": tot_fatt,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["_sort_paia", "_sort_fatt"], ascending=False).drop(
        columns=["_sort_paia", "_sort_fatt"]).reset_index(drop=True)
