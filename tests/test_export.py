"""L'export deve quadrare col Fatturato: per scope, per mese, e includere i resi fuori periodo."""
import datetime as dt

import pytest

from core import db, export, metrics
from tests.conftest import carica, riga

PERIODO = (dt.date(2026, 1, 1), dt.date(2026, 2, 28))


@pytest.fixture
def periodi(conn):
    carica(conn,
           dataset=[riga("A1", "10/01/2026"), riga("A2", "12/02/2026", naz="DE", mkp="Zalando"),
                    riga("B1", "28/12/2025")],
           resi=[riga("A1", "10/01/2026", data_reso="20/01/2026", stato="Reso"),
                 riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso"),
                 # reso di un ordine mai caricato, in una nazione/mkp che il venduto non ha
                 riga("X9", "15/12/2025", data_reso="05/02/2026", stato="Reso", naz="FR", mkp="Amazon")])
    venduto, resi_fp = db.query_period(conn, *PERIODO)
    return [("2026", venduto, resi_fp)]


def test_ogni_scope_somma_al_fatturato_reale(periodi):
    _, venduto, resi_fp = periodi[0]
    atteso = metrics.kpi_reali(venduto, resi_fp)["fattReale"]
    df = export.build_export(periodi, export.nazioni_disponibili(periodi))
    for scope in export.SCOPES:
        assert df.loc[df["Scope"] == scope, "Fatturato"].sum() == pytest.approx(atteso), scope


def test_mensile_somma_al_totale_del_periodo(periodi):
    nazioni = export.nazioni_disponibili(periodi)
    tot = export.build_export(periodi, nazioni)
    mens = export.build_export(periodi, nazioni, mensile=True)
    assert set(mens["Mese"]) <= {"Gennaio", "Febbraio"}
    for scope in export.SCOPES:
        assert (mens.loc[mens["Scope"] == scope, "Fatturato"].sum()
                == pytest.approx(tot.loc[tot["Scope"] == scope, "Fatturato"].sum()))


def test_il_reso_fuori_periodo_di_una_nazione_nuova_compare_nel_dettaglio(periodi):
    df = export.build_export(periodi, export.nazioni_disponibili(periodi))
    riga_fr = df[(df["Scope"] == "GLOBAL_COUNTRY") & (df["Nazione"] == "FR")]
    assert len(riga_fr) == 1 and riga_fr["Fatturato"].iloc[0] == pytest.approx(-100.0)


def test_formati_csv_e_markdown(periodi):
    df = export.build_export(periodi, export.nazioni_disponibili(periodi))
    assert export.to_csv(df).startswith(b"\xef\xbb\xbfAnno;Mese;Scope")
    md = export.to_markdown(df)
    assert md.splitlines()[0].startswith("| Anno | Mese | Scope")
