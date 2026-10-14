import plotly.express as px
import streamlit as st
import pandas as pd

from core import aggregations as agg
from core import metrics as met
from core import report_builders as rb
from core.design_system import page_setup, section, data_table, chart, metric_cards, empty_state, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels

page_setup("Canali & Marketplace", None)

pipe = guard_pipeline()
y_curr, y_old = period_labels(2)
ha_vecchio = not pipe.old_data.empty

current_data = pipe.current_data
old_data = pipe.old_data
st_curr = pipe.resi_fp_current
st_old = pipe.resi_fp_old

# Predicati di canale
pred_dir = lambda df: df["tipoSpedizione"] != "ESTERNA" if not df.empty else df.index < 0
pred_est = lambda df: df["tipoSpedizione"] == "ESTERNA" if not df.empty else df.index < 0
pred_zfs = lambda df: df["ordineId"].str.contains("_ZFS", na=False) if not df.empty else df.index < 0

kpi_tot_curr = met.compute_channel_kpi(current_data, st_curr)
kpi_dir_curr = met.compute_channel_kpi(current_data, st_curr, pred_dir)
kpi_est_curr = met.compute_channel_kpi(current_data, st_curr, pred_est)
kpi_zfs_curr = met.compute_channel_kpi(current_data, st_curr, pred_zfs)

share_dir = (kpi_dir_curr["fattReale"] / kpi_tot_curr["fattReale"]) if kpi_tot_curr["fattReale"] > 0 else 0.0
share_est = (kpi_est_curr["fattReale"] / kpi_tot_curr["fattReale"]) if kpi_tot_curr["fattReale"] > 0 else 0.0

metric_cards([
    {"label": f"Fatturato ({y_curr})", "value": f"{it_num(kpi_tot_curr['fattReale'], 2)} €"},
    {"label": f"Canale Diretto (Share {it_num(share_dir*100, 1)}%)", "value": f"{it_num(kpi_dir_curr['fattReale'], 2)} €"},
    {"label": f"Marketplace Esterni (Share {it_num(share_est*100, 1)}%)", "value": f"{it_num(kpi_est_curr['fattReale'], 2)} €"},
    {"label": "Di cui Zalando ZFS", "value": f"{it_num(kpi_zfs_curr['fattReale'], 2)} €"},
    {"label": "% Reso Diretto (Paia)", "value": f"{it_num(kpi_dir_curr['percReso']*100, 1)}%"},
    {"label": "% Reso Marketplace (Paia)", "value": f"{it_num(kpi_est_curr['percReso']*100, 1)}%"},
])

st.divider()

section("Confronto Macro-Canali Y2Y")
canali_rows = []
for nome, pred in [("DIRETTO", pred_dir), ("ESTERNO (Marketplace)", pred_est), ("— di cui ZALANDO ZFS", pred_zfs)]:
    c_kpi = met.compute_channel_kpi(current_data, st_curr, pred)
    o_kpi = met.compute_channel_kpi(old_data, st_old, pred) if ha_vecchio else None

    var_f = rb.var_pct(c_kpi["fattReale"], o_kpi["fattReale"]) if ha_vecchio and o_kpi else 0.0
    var_p = rb.var_pct(c_kpi["paiaNette"], o_kpi["paiaNette"]) if ha_vecchio and o_kpi else 0.0

    row = {
        "Canale": nome,
        f"Fatturato {y_curr}": c_kpi["fattReale"],
        f"Fatturato {y_old}": o_kpi["fattReale"] if o_kpi else 0.0,
        "VAR% FATT": var_f,
        f"Paia Nette {y_curr}": c_kpi["paiaNette"],
        f"Paia Nette {y_old}": o_kpi["paiaNette"] if o_kpi else 0.0,
        "VAR% PAIA": var_p,
        f"Val. Medio Paio {y_curr}": c_kpi["valMedio"],
        f"Scontrino Medio {y_curr}": c_kpi["scontrinoMedio"],
        f"% Reso Paia {y_curr}": c_kpi["percReso"],
        f"% Reso Valore {y_curr}": c_kpi["percResoValore"],
    }
    canali_rows.append(row)

df_canali = pd.DataFrame(canali_rows)
data_table(df_canali, {
    f"Fatturato {y_curr}": currency_col(),
    f"Fatturato {y_old}": currency_col(),
    "VAR% FATT": percent_col(),
    "VAR% PAIA": percent_col(),
    f"Paia Nette {y_curr}": number_col(),
    f"Paia Nette {y_old}": number_col(),
    f"Val. Medio Paio {y_curr}": currency_col(),
    f"Scontrino Medio {y_curr}": currency_col(),
    f"% Reso Paia {y_curr}": percent_col(),
    f"% Reso Valore {y_curr}": percent_col(),
})

section("Dettaglio per Singolo Marketplace (Piattaforma)")
if ha_vecchio:
    agg_mkp_c = agg.aggregate_by_key(current_data, "mkp", st_curr)
    agg_mkp_o = agg.aggregate_by_key(old_data, "mkp", st_old)
    df_mkp = rb.comparative_table(agg_mkp_c, agg_mkp_o, y_curr, y_old, "fatturatoNetto")
    data_table(df_mkp, {
        f"Fatturato {y_curr}": currency_col(),
        f"Fatturato {y_old}": currency_col(),
        "VAR% FATT": percent_col(),
        f"Paia Nette {y_curr}": number_col(),
        f"Paia Nette {y_old}": number_col(),
        f"Scontrino Medio {y_curr}": currency_col(),
        f"Scontrino Medio {y_old}": currency_col(),
        f"% Reso {y_curr}": percent_col(),
    })
else:
    agg_mkp_c = agg.aggregate_by_key(current_data, "mkp", st_curr)
    df_mkp = rb.single_year_table(agg_mkp_c, y_curr, "fatturatoNetto")
    data_table(df_mkp, {
        f"Fatturato {y_curr}": currency_col(),
        "Valore Medio Paio": currency_col(),
        "Scontrino Medio": currency_col(),
        "% Reso": percent_col(),
        "Paia Spedite": number_col(),
        "Paia Rese": number_col(),
        "Paia Nette": number_col(),
    })

section("Trend Mensile per Canale")
# Calcolo trend mensile aggregato per Diretti vs Esterni
if not current_data.empty and "dataVendita" in current_data.columns:
    # venduto per mese di vendita + resi fuori periodo per mese di reso: la somma è il Fatturato
    cd = pd.concat([d for d in (current_data.assign(_data=current_data["dataVendita"]),
                                st_curr.assign(_data=st_curr["dataReso"])) if not d.empty], ignore_index=True)
    cd = cd[cd["_data"].notna()].copy()
    cd["_mese"] = cd["_data"].dt.strftime("%Y-%m")
    cd["_canale"] = cd["tipoSpedizione"].apply(lambda t: "ESTERNO (Marketplace)" if t == "ESTERNA" else "DIRETTO")

    trend_m = cd.groupby(["_mese", "_canale"], sort=True, observed=True)["nettoNetto"].sum().reset_index()
    if not trend_m.empty:
        fig_trend = px.bar(
            trend_m,
            x="_mese",
            y="nettoNetto",
            color="_canale",
            barmode="group",
            labels={"_mese": "Mese di Vendita", "nettoNetto": "Fatturato (€)", "_canale": "Canale"},
            title="Distribuzione Fatturato per Mese e Canale",
        )
        fig_trend.update_layout(legend_title_text="Canale")
        chart(fig_trend, y_title="Fatturato (€)")
