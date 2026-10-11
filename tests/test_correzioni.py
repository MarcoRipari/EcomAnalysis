"""Trova e sostituisci sul DB: anteprima, condizioni, chiavi di riconciliazione, regole permanenti."""
import datetime as dt

import pandas as pd
import pytest

from core import correzioni as cz
from core import db
from tests.conftest import carica, riga, to_processed


def nazioni(conn) -> dict:
    return dict(conn.execute("SELECT nazione, COUNT(*) FROM righe GROUP BY nazione").fetchall())


@pytest.fixture
def dbc(conn):
    carica(conn, dataset=[riga("A1", "10/01/2026", naz="UNITED KIN"),
                          riga("A2", "11/01/2026", naz="United Kin", mkp="Zalando"),
                          riga("A3", "12/03/2026", naz="UNITED KIN", mkp="Zalando"),
                          riga("A4", "13/01/2026", naz="IT"),
                          riga("A5", "14/01/2026", naz="")])
    return conn


def regola(**kw):
    base = dict(colonna="nazione", operatore="uguale a", cerca="UNITED KIN", sostituisci="GB")
    base.update(kw)
    return cz.Regola(**base)


def test_anteprima_non_modifica_e_mostra_la_mappa(dbc):
    prima = nazioni(dbc)
    a = cz.anteprima(dbc, regola())
    assert a["totale"] == 3
    assert set(a["mappa"]["Valore attuale"]) == {"UNITED KIN", "UNITED KIN"} or a["mappa"]["Righe"].sum() == 3
    assert (a["mappa"]["Nuovo valore"] == "GB").all()
    assert nazioni(dbc) == prima


def test_applica_esempio_united_kin_diventa_gb(dbc):
    assert cz.applica(dbc, regola()) == 3
    assert nazioni(dbc).get("GB") == 3 and "UNITED KIN" not in nazioni(dbc)
    assert nazioni(dbc)["IT"] == 1


def test_maiuscole_rispettate_se_richiesto(dbc):
    dbc.execute("UPDATE righe SET nazione='United Kin' WHERE ordine_id='A2'")   # il motore normalizza in maiuscolo
    assert cz.applica(dbc, regola(ignora_maiuscole=False)) == 2     # "United Kin" escluso
    assert cz.applica(dbc, regola(ignora_maiuscole=True, cerca="united kin")) == 1


def test_condizioni_marketplace_e_date(dbc):
    r = regola(condizioni=[{"colonna": "mkp", "operatore": "uguale a", "valore": "Zalando"}],
               data_da="2026-01-01", data_a="2026-01-31")
    assert cz.applica(dbc, r) == 1                                   # solo A2: A3 è di marzo, A1 non è Zalando
    assert nazioni(dbc).get("GB") == 1


def test_modo_testo_sostituisce_solo_la_parte_trovata(conn):
    carica(conn, dataset=[riga("A1", "10/01/2026", naz="UNITED KINGDOM X")])
    cz.applica(conn, cz.Regola("nazione", "contiene", "kingdom", "KD", modo="testo"))
    assert nazioni(conn) == {"UNITED KD X": 1}


def test_valori_vuoti(dbc):
    assert cz.applica(dbc, cz.Regola("nazione", "è vuoto", "", "IT")) == 1
    assert nazioni(dbc)["IT"] == 2


def test_colonne_non_ammesse_sono_rifiutate(dbc):
    with pytest.raises(ValueError):
        cz.applica(dbc, regola(colonna="id; DROP TABLE righe"))
    with pytest.raises(ValueError):
        cz.applica(dbc, regola(colonna="acquirente"))                # fa parte dell'id della riga
    with pytest.raises(ValueError):
        cz.applica(dbc, regola(condizioni=[{"colonna": "x", "operatore": "uguale a", "valore": "1"}]))
    with pytest.raises(ValueError):
        cz.applica(dbc, regola(cerca=""))
    assert dbc.execute("SELECT COUNT(*) FROM righe").fetchone()[0] == 5


def test_dopo_la_correzione_i_resi_agganciano_con_la_chiave_composita(conn):
    """L'ordine del reso ha un numero diverso: l'aggancio avviene su mkp+nazione+acquirente+sku+taglia+importo."""
    carica(conn, dataset=[riga("ORD-1", "10/01/2026", naz="UNITED KIN")])
    cz.applica(conn, regola())
    esito = db.upsert_resi(conn, to_processed([riga("ALTRO-9", "10/01/2026", data_reso="20/01/2026",
                                                    stato="Reso", naz="GB")]), "resi.csv")
    assert esito["convertiti"] == 1 and esito["senza_ordine"] == 0


def test_ricarico_dello_stesso_file_non_duplica_dopo_la_correzione(conn):
    righe = [riga("A1", "10/01/2026", naz="UNITED KIN")]
    carica(conn, dataset=righe)
    cz.applica(conn, regola())
    carica(conn, dataset=righe)
    assert conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0] == 1


def test_regola_salvata_si_applica_ai_nuovi_caricamenti(conn):
    cz.salva_regola(conn, regola())
    carica(conn, dataset=[riga("N1", "10/02/2026", naz="UNITED KIN")])
    assert nazioni(conn) == {"GB": 1}
    carica(conn, resi=[riga("N2", "11/02/2026", data_reso="12/02/2026", stato="Reso", naz="UNITED KIN",
                            sku="ZZZZZZZ111111-37")])
    assert nazioni(conn) == {"GB": 2}                                # il reso senza ordine ha ricevuto la stessa regola
    rid = cz.elenco_regole(conn)["ID"].iloc[0]
    cz.elimina_regola(conn, rid)
    carica(conn, dataset=[riga("N3", "11/02/2026", naz="UNITED KIN")])
    assert nazioni(conn).get("UNITED KIN") == 1


def test_regole_con_condizioni_solo_db_non_si_salvano(conn):
    r = regola(condizioni=[{"colonna": "status", "operatore": "uguale a", "valore": "Reso"}])
    assert not r.salvabile
    with pytest.raises(ValueError):
        cz.salva_regola(conn, r)


@pytest.mark.parametrize("operatore,valore", [("uguale a", "united kin"), ("diverso da", "UNITED KIN"),
                                              ("contiene", "ited"), ("non contiene", "ited"),
                                              ("inizia con", "uni"), ("finisce con", "kin"),
                                              ("è vuoto", ""), ("non è vuoto", "")])
@pytest.mark.parametrize("ci", [True, False])
def test_sql_e_pandas_danno_gli_stessi_risultati(dbc, operatore, valore, ci):
    r = cz.Regola("nazione", operatore, valore, "XX", ignora_maiuscole=ci)
    where, params = cz._where_sql(r)
    ids_sql = {row[0] for row in dbc.execute(f"SELECT ordine_id FROM righe WHERE {where}", params)}
    df = pd.read_sql_query("SELECT ordine_id, nazione FROM righe", dbc)
    mask = cz._mask_df(df["nazione"], operatore, valore, ci)
    assert ids_sql == set(df.loc[mask, "ordine_id"])
