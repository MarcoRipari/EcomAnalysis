"""Variazioni %, etichette dei periodi e Scontrino Medio: formule e formati."""
import datetime as dt
import math

import pandas as pd
import pytest

from core import export, metrics, pipeline
from core import report_builders as rb
from core.formatting import etichetta_periodo, fmt_pp, fmt_var
from tests.conftest import carica, riga


def test_variazione_del_caso_segnalato():
    assert rb.var_pct(15145406.82, 14668552.12) == pytest.approx(0.03251, abs=1e-5)
    assert fmt_var(rb.var_pct(15145406.82, 14668552.12)) == "+3,3%"


def test_variazione_base_zero_o_negativa():
    assert math.isnan(rb.var_pct(100, 0))                       # non calcolabile, non "100%"
    assert rb.var_pct(-50, -100) == pytest.approx(0.5)          # da -100 a -50 è un miglioramento
    assert rb.var_pct(-150, -100) == pytest.approx(-0.5)
    assert fmt_var(float("nan")) == "—"


def test_kpi_block_le_percentuali_sono_punti_non_variazioni_relative():
    kc = dict(fattReale=15145406.82, paiaNette=1000, valMedio=15.1, scontrinoMedio=60.0, percReso=0.24, paiaSped=10)
    ko = dict(fattReale=14668552.12, paiaNette=900, valMedio=16.0, scontrinoMedio=50.0, percReso=0.22, paiaSped=10)
    blocco = rb.kpi_block(kc, ko, "2026", "2025").set_index("Metrica")
    assert blocco.loc["FATTURATO", "Var % Y2Y"] == "+3,3%"
    assert blocco.loc["PAIA NETTE VENDUTE", "Var % Y2Y"] == "+11,1%"
    assert blocco.loc["VALORE MEDIO PAIO", "Var % Y2Y"] == "-5,6%"
    assert blocco.loc["SCONTRINO MEDIO", "Var % Y2Y"] == "+20,0%"
    assert blocco.loc["% RESO", "Var % Y2Y"] == fmt_pp(0.02) == "+2,0 pp"
    assert blocco.loc["% RESO", "2026"] == "24,0%"


def test_etichette_periodo():
    # tabelle: l'anno dell'ultima data del periodo
    assert etichetta_periodo(dt.date(2026, 1, 1), dt.date(2026, 6, 30)) == "2026"
    assert etichetta_periodo(dt.date(2025, 11, 1), dt.date(2026, 10, 31)) == "2026"
    assert etichetta_periodo(dt.date(2025, 11, 1), dt.date(2026, 10, 31), 1) == "2025"
    assert etichetta_periodo(dt.date(2025, 11, 1), dt.date(2026, 10, 31), 2) == "2024"
    # grafici: intervallo di anni per i periodi a cavallo d'anno
    assert etichetta_periodo(dt.date(2025, 11, 1), dt.date(2026, 10, 31), lunga=True) == "2025/26"
    assert etichetta_periodo(dt.date(2025, 11, 1), dt.date(2026, 10, 31), 1, lunga=True) == "2024/25"
    assert etichetta_periodo(dt.date(2026, 1, 1), dt.date(2026, 6, 30), lunga=True) == "2026"


def test_percentuali_nelle_tabelle_sono_frazioni_coerenti(conn):
    carica(conn, dataset=[riga("A1", "10/01/2026"), riga("A2", "11/01/2026"), riga("A3", "12/01/2026")],
           resi=[riga("A1", "10/01/2026", data_reso="20/01/2026", stato="Reso")])
    pipe = pipeline.build_pipeline_from_db(conn, (dt.date(2026, 1, 1), dt.date(2026, 1, 31)), None)
    k = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)
    assert k["percReso"] == pytest.approx(1 / 3)
    t = rb.nazioni_metrics(pipe.current_data, pipe.resi_fp_current, ["GLOBAL"])
    assert t["% Reso"].iloc[0] == pytest.approx(1 / 3)


def test_scontrino_medio_e_netto_spedito_per_ordine(conn):
    carica(conn, dataset=[riga("A1", "10/01/2026", importo="121,00"),
                          riga("A2", "11/01/2026", importo="242,00")],
           resi=[riga("A2", "11/01/2026", data_reso="20/01/2026", stato="Reso", importo="242,00")])
    pipe = pipeline.build_pipeline_from_db(conn, (dt.date(2026, 1, 1), dt.date(2026, 1, 31)), None)
    k = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)
    assert k["scontrinoMedio"] == pytest.approx((100 + 200) / 2)      # prima dei resi
    from core import aggregations as agg
    tab = rb.single_year_table(agg.aggregate_by_key(pipe.current_data, "mkp", pipe.resi_fp_current), "2026")
    assert tab["Scontrino Medio"].iloc[0] == pytest.approx(150.0)
    mesi, stagioni = rb.monthly_season_report(dt.date(2026, 1, 1), dt.date(2026, 1, 31),
                                              [("2026", pipe.current_data, pipe.resi_fp_current)])
    assert mesi["Scontrino Medio 2026"].iloc[0] == pytest.approx(150.0)
    assert stagioni["Scontrino Medio 2026"].iloc[0] == pytest.approx(150.0)
    cmp = rb.comparative_table(agg.aggregate_by_key(pipe.current_data, "mkp", pipe.resi_fp_current),
                               agg.aggregate_by_key(pipe.old_data, "mkp"), "2026", "2025")
    assert cmp["Scontrino Medio 2026"].iloc[0] == pytest.approx(150.0)


def test_report_mensile_su_periodo_a_cavallo_d_anno_etichetta_il_primo_mese(conn):
    carica(conn, dataset=[riga("A1", "10/11/2025"), riga("A2", "10/11/2024")])
    periodo, precedente = (dt.date(2025, 11, 1), dt.date(2026, 9, 30)), (dt.date(2024, 11, 1), dt.date(2025, 9, 30))
    pipe = pipeline.build_pipeline_from_db(conn, periodo, precedente)
    cur, old = etichetta_periodo(*periodo), etichetta_periodo(*periodo, 1)      # etichette brevi delle tabelle
    mesi, _ = rb.monthly_season_report(*periodo, [(cur, pipe.current_data, pipe.resi_fp_current),
                                                  (old, pipe.old_data, pipe.resi_fp_old)])
    assert mesi["Mese"].iloc[0] == "Novembre"
    assert mesi[f"Fatturato {cur}"].iloc[0] == pytest.approx(100.0)     # novembre 2025
    assert mesi[f"Fatturato {old}"].iloc[0] == pytest.approx(100.0)     # novembre 2024
    assert (cur, old) == ("2026", "2025")
    assert (etichetta_periodo(*periodo, lunga=True), etichetta_periodo(*periodo, 1, lunga=True)) == ("2025/26", "2024/25")


def test_csv_dell_export_ha_le_percentuali_in_punti():
    df = pd.DataFrame([{"Anno": "2026", "Mese": "x", "Scope": "GLOBAL", "Marketplace": "g", "Nazione": "g",
                        "Brand": "g", "Fatturato": 1000.0, "Share %": 0.5, "Valore Medio Paio": 10.0,
                        "Paia spedite": 1.0, "Paia rese": 0.0, "Paia nette": 1.0, "Reso %": 0.2234,
                        "Reso % (valore)": 0.1, "Var % Fatturato YoY": None}])
    csv = export.to_csv(df).decode("utf-8-sig")
    assert "22,3400" in csv and "50,0000" in csv
