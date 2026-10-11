"""Paia nette mai negative: spedite 0 e rese 17 (resi di vendite fuori periodo) ⇒ 0, non −17."""
import datetime as dt

import pytest

from core import aggregations as agg
from core import export, metrics, pipeline, sku_search as sk
from core import report_builders as rb
from tests.conftest import carica, riga

PERIODO = (dt.date(2026, 1, 1), dt.date(2026, 1, 31))


@pytest.fixture
def pipe(conn):
    # un articolo venduto a gennaio (2 paia) e un altro SOLO reso a gennaio (17 paia) ma venduto a dicembre
    carica(conn,
           dataset=[riga("A1", "10/01/2026", qta="2", importo="242,00"),
                    riga("B1", "20/12/2025", qta="17", importo="2057,00", sku="ZZZZZZZ111111-37", mkp="Zalando", naz="DE")],
           resi=[riga("B1", "20/12/2025", data_reso="15/01/2026", stato="Reso", qta="17", importo="2057,00",
                      sku="ZZZZZZZ111111-37", mkp="Zalando", naz="DE")])
    return pipeline.build_pipeline_from_db(conn, PERIODO, None)


def test_solo_resi_fuori_periodo_le_paia_nette_sono_zero(pipe):
    assert pipe.resi_fp_current["paiaRese"].sum() == 17
    for chiave in ("mkp", "nazione", "sku13", "sku7", "clzMappata"):
        a = agg.aggregate_by_key(pipe.current_data, chiave, pipe.resi_fp_current)
        assert all(v["paiaNette"] >= 0 for v in a["map"].values()), chiave
    zal = agg.aggregate_by_key(pipe.current_data, "mkp", pipe.resi_fp_current)["map"]["Zalando"]
    assert zal["paiaSpedite"] == 0 and zal["paiaRese"] == 17 and zal["paiaNette"] == 0
    assert zal["fatturatoNetto"] == pytest.approx(-1700.0)          # il fatturato resta quello reale


def test_kpi_e_tabelle(pipe):
    k = metrics.kpi_per_canale(pipe.current_data, pipe.resi_fp_current)
    assert k["tot"]["paiaNette"] == 0 and k["tot"]["valMedio"] == 0     # 2 spedite − 17 rese = −15 ⇒ 0
    solo_zal = metrics.compute_channel_kpi(pipe.current_data, pipe.resi_fp_current,
                                           lambda d: d["mkp"].astype(str) == "Zalando")
    assert solo_zal["paiaNette"] == 0 and solo_zal["valMedio"] == 0
    t = rb.nazioni_metrics(pipe.current_data, pipe.resi_fp_current, ["DE", "GLOBAL"])
    assert (t["Paia Nette"] >= 0).all()
    share = rb.nazioni_brand_share(pipe.current_data, "DE", pipe.resi_fp_current)
    assert (share["Paia nette"] >= 0).all()
    top = rb.top_articoli_dashboard(pipe.current_data, {}, resi_fp_data=pipe.resi_fp_current)
    assert (top["Paia Nette"] >= 0).all()
    cod = rb.comparativa_codici(pipe.current_data, pipe.old_data, {}, "2026", "2025",
                                resi_fp_current=pipe.resi_fp_current, resi_fp_old=pipe.resi_fp_old)
    assert (cod["Paia Net 2026"] >= 0).all()
    mesi, _ = rb.monthly_season_report(PERIODO[0], PERIODO[1], [("2026", pipe.current_data, pipe.resi_fp_current)])
    assert (mesi["Paia Nette 2026"] >= 0).all()
    tg = agg.aggregate_by_taglia_per_brand(pipe.current_data, pipe.resi_fp_current)
    assert all(d["paiaNette"] >= 0 for g in tg.values() for t in g.values() for d in t.values())
    tree = agg.aggregate_hierarchical_custom(pipe.current_data, ["clzMappata", "mkp"], None,
                                             resi_fp_df=pipe.resi_fp_current)["tree"]
    assert all(n["paiaNette"] >= 0 and all(c["paiaNette"] >= 0 for c in n["kids"].values()) for n in tree.values())


def test_export_e_trova_sku(pipe):
    df = export.build_export([("2026", pipe.current_data, pipe.resi_fp_current)], ["DE", "IT"])
    assert (df["Paia nette"] >= 0).all()
    t = sk.tabella_per(pipe.current_data, pipe.resi_fp_current, "Marketplace")
    assert (t["Paia nette"] >= 0).all() and (t["Valore Medio Paio"] >= 0).all()
