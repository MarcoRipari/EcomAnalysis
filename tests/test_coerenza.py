"""Un solo Fatturato: tutte le tabelle e le pagine devono sommare allo stesso numero."""
import datetime as dt

import pytest

from core import aggregations as agg
from core import db, metrics, pipeline
from core import report_builders as rb
from tests.conftest import carica, riga

PERIODO = (dt.date(2026, 1, 1), dt.date(2026, 3, 31))
PRECEDENTE = (dt.date(2025, 1, 1), dt.date(2025, 3, 31))


@pytest.fixture
def pipe(conn):
    carica(conn,
           dataset=[riga("A1", "10/01/2026"), riga("A2", "12/02/2026", naz="DE", mkp="Zalando", sku="ABCDEFG123999-36"),
                    riga("A3", "03/03/2026", mkp="Amazon_ZFS", naz="FR", sku="ZZZZZZZ111111-37"),
                    riga("B1", "28/12/2025"), riga("C1", "05/02/2025"),
                    riga("C2", "20/02/2025", mkp="Zalando", naz="DE", sku="ABCDEFG123999-36")],
           resi=[riga("A1", "10/01/2026", data_reso="20/01/2026", stato="Reso"),
                 riga("A3", "03/03/2026", data_reso="20/04/2026", stato="Reso", mkp="Amazon_ZFS", naz="FR",
                      sku="ZZZZZZZ111111-37"),
                 riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso"),
                 riga("C1", "05/02/2025", data_reso="10/05/2025", stato="Reso"),
                 riga("X9", "15/12/2025", data_reso="05/02/2026", stato="Reso", naz="IT", mkp="Zalando")])
    return pipeline.build_pipeline_from_db(conn, PERIODO, PRECEDENTE, "1", {})


def test_fatturato_reale_atteso(pipe):
    # A1 (vendita+reso nel periodo → 0) + A2 (100) + A3 (reso ad aprile → ancora spedito, 100)
    # − B1 (vendita dicembre, reso gennaio) − X9 (ordine ignoto, reso febbraio)
    k = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)
    assert k["fattReale"] == pytest.approx(100 + 100 - 100 - 100)
    assert k["lordo"] == pytest.approx(3 * 121)


def test_la_composizione_quadra(pipe):
    k = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)
    assert k["nettoSpedito"] - k["resiPeriodo"] - k["resiFuoriPeriodo"] == pytest.approx(k["fattReale"])


def test_canali_sommano_al_totale(pipe):
    kc = metrics.kpi_per_canale(pipe.current_data, pipe.resi_fp_current)
    assert kc["dir"]["fattReale"] + kc["est"]["fattReale"] == pytest.approx(kc["tot"]["fattReale"])
    assert kc["dir"]["paiaNette"] + kc["est"]["paiaNette"] == pytest.approx(kc["tot"]["paiaNette"])


@pytest.mark.parametrize("chiave", ["mkp", "nazione", "clzMappata", "sku13", "sku7"])
def test_aggregazioni_sommano_al_fatturato_reale(pipe, chiave):
    totale = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)["fattReale"]
    a = agg.aggregate_by_key(pipe.current_data, chiave, pipe.resi_fp_current)
    assert sum(v["fatturatoNetto"] for v in a["map"].values()) == pytest.approx(totale)
    assert a["total"] == pytest.approx(totale)


def test_nazioni_global_coincide_con_dashboard(pipe):
    totale = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)["fattReale"]
    t = rb.nazioni_metrics(pipe.current_data, pipe.resi_fp_current, ["GLOBAL"])
    assert t["Fatturato"].iloc[0] == pytest.approx(totale)
    nazioni = rb.nazioni_disponibili(pipe.current_data, pipe.resi_fp_current)
    per_naz = rb.nazioni_metrics(pipe.current_data, pipe.resi_fp_current, nazioni)
    assert per_naz["Fatturato"].sum() == pytest.approx(totale)
    share = rb.nazioni_brand_share(pipe.current_data, "GLOBAL", pipe.resi_fp_current)
    assert share["Fatturato"].sum() == pytest.approx(totale)


def test_report_mensile_somma_al_totale(pipe):
    totale = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)["fattReale"]
    mesi, _ = rb.monthly_season_report(PERIODO[0], PERIODO[1],
                                       [("2026", pipe.current_data, pipe.resi_fp_current)])
    assert mesi["Fatturato 2026"].sum() == pytest.approx(totale)


def test_top_articoli_sommano_al_fatturato_reale(pipe):
    totale = metrics.kpi_reali(pipe.current_data, pipe.resi_fp_current)["fattReale"]
    top = rb.top_articoli_dashboard(pipe.current_data, {}, resi_fp_data=pipe.resi_fp_current)
    assert top["Fatturato"].sum() == pytest.approx(totale)
    y2y = rb.top_articoli_y2y(pipe.current_data, pipe.old_data, {}, "2026", "2025", top_n=1000,
                              resi_fp_current=pipe.resi_fp_current, resi_fp_old=pipe.resi_fp_old)
    assert y2y["Fatturato 2026"].sum() == pytest.approx(totale)
    codici = rb.comparativa_codici(pipe.current_data, pipe.old_data, {}, "2026", "2025",
                                   resi_fp_current=pipe.resi_fp_current, resi_fp_old=pipe.resi_fp_old)
    assert codici["Fatturato 2026"].sum() == pytest.approx(totale)


def test_report_mensile_coincide_con_singolo_mese_dashboard(conn):
    """Verifica che un reso a cavallo tra due mesi (vendita a gennaio, reso a febbraio)
    venga conteggiato a febbraio (mese del reso), sia interrogando il singolo mese che
    nel report mensile Y2Y del periodo cumulativo."""
    carica(conn,
           dataset=[riga("V1", "15/01/2026"),
                    riga("V2", "20/01/2026"),
                    riga("V3", "10/02/2026")],
           resi=[riga("V1", "15/01/2026", data_reso="10/02/2026", stato="Reso")])
    m_gen = (dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    m_feb = (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    m_tot = (dt.date(2026, 1, 1), dt.date(2026, 2, 28))

    # Singolo mese Gennaio: 2 vendite, 0 resi (il reso è a febbraio)
    v_gen, s_gen = db.query_period(conn, *m_gen)
    k_gen = metrics.kpi_reali(v_gen, s_gen)
    assert k_gen["paiaSped"] == 2 and k_gen["paiaRes"] == 0
    assert k_gen["paiaNette"] == 2
    assert k_gen["fattReale"] == pytest.approx(200.0)

    # Singolo mese Febbraio: 1 vendita, 1 reso fuori periodo (V1 venduto a gen)
    v_feb, s_feb = db.query_period(conn, *m_feb)
    k_feb = metrics.kpi_reali(v_feb, s_feb)
    assert k_feb["paiaSped"] == 1 and k_feb["paiaRes"] == 1
    assert k_feb["paiaNette"] == 0
    assert k_feb["fattReale"] == pytest.approx(0.0)

    # Periodo cumulativo Gen-Feb: report mensile Y2Y
    v_tot, s_tot = db.query_period(conn, *m_tot)
    mesi_df, _ = rb.monthly_season_report(m_tot[0], m_tot[1], [("2026", v_tot, s_tot)])

    # Riga Gennaio nel report deve coincidere con k_gen
    r_gen = mesi_df[mesi_df["Mese"] == "Gennaio"].iloc[0]
    assert r_gen["Fatturato 2026"] == pytest.approx(k_gen["fattReale"])
    assert r_gen["Paia Nette 2026"] == k_gen["paiaNette"]

    # Riga Febbraio nel report deve coincidere con k_feb
    r_feb = mesi_df[mesi_df["Mese"] == "Febbraio"].iloc[0]
    assert r_feb["Fatturato 2026"] == pytest.approx(k_feb["fattReale"])
    assert r_feb["Paia Nette 2026"] == k_feb["paiaNette"]

