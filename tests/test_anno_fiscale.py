"""Periodo di default: anno fiscale aziendale (1 novembre → 31 ottobre), limitato ai dati disponibili."""
import datetime as dt

from core.topbar import anno_fiscale, periodo_predefinito

D = dt.date


def test_anno_fiscale_che_contiene_oggi():
    assert anno_fiscale(D(2026, 10, 11)) == (D(2025, 11, 1), D(2026, 10, 31))
    assert anno_fiscale(D(2026, 11, 1)) == (D(2026, 11, 1), D(2027, 10, 31))
    assert anno_fiscale(D(2026, 1, 15)) == (D(2025, 11, 1), D(2026, 10, 31))
    assert anno_fiscale(D(2026, 10, 11), indietro=1) == (D(2024, 11, 1), D(2025, 10, 31))


def test_default_si_ferma_all_ultimo_dato_disponibile():
    assert periodo_predefinito(D(2026, 10, 11), D(2024, 1, 1), D(2026, 6, 28)) == (D(2025, 11, 1), D(2026, 6, 28))


def test_default_a_fine_anno_fiscale_con_dati_completi():
    assert periodo_predefinito(D(2026, 10, 11), D(2024, 1, 1), D(2026, 10, 31)) == (D(2025, 11, 1), D(2026, 10, 31))


def test_default_inizia_dal_primo_dato_se_il_db_parte_dopo():
    assert periodo_predefinito(D(2026, 10, 11), D(2026, 2, 10), D(2026, 6, 28)) == (D(2026, 2, 10), D(2026, 6, 28))


def test_nuovo_anno_fiscale_senza_dati_usa_il_precedente():
    # il 15/11/2026 è iniziato l'anno fiscale 2026/27 ma gli ultimi dati sono al 31/10/2026
    assert periodo_predefinito(D(2026, 11, 15), D(2024, 1, 1), D(2026, 10, 31)) == (D(2025, 11, 1), D(2026, 10, 31))


def test_db_vecchio_ripiega_sugli_ultimi_12_mesi_di_dati():
    assert periodo_predefinito(D(2030, 5, 1), D(2020, 1, 1), D(2021, 3, 31)) == (D(2020, 3, 31), D(2021, 3, 31))
