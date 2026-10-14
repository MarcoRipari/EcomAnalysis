import pytest
from core import roles, db

def test_roles_initialization(conn):
    roles.init_roles(conn)
    all_roles = roles.get_all_roles(conn)
    nomi = [r["nome"] for r in all_roles]
    assert "Admin" in nomi
    assert "Finance" in nomi
    assert "Logistica" in nomi

    # Admin ha tutte le pagine
    admin_perms = roles.get_role_permissions(conn, "Admin")
    assert len(admin_perms) == len(roles.ALL_PAGE_IDS)
    assert "16_Gestione_Ruoli" in admin_perms

    # Finance non ha pagine admin di sistema
    fin_perms = roles.get_role_permissions(conn, "Finance")
    assert "01_Dashboard" in fin_perms
    assert "16_Gestione_Ruoli" not in fin_perms
    assert "13_Correzioni_DB" not in fin_perms

    # Logistica ha catalogo e foto, ma non dashboard o ruoli
    log_perms = roles.get_role_permissions(conn, "Logistica")
    assert "20_Catalogo_Panoramica" in log_perms
    assert "22_Foto_Archivio" in log_perms
    assert "01_Dashboard" not in log_perms
    assert "16_Gestione_Ruoli" not in log_perms


def test_create_and_delete_role(conn):
    roles.init_roles(conn)
    ok, msg = roles.create_role(conn, "Commerciale", "Ruolo commerciale vendite", ["00_Home", "01_Dashboard"])
    assert ok is True

    comm_perms = roles.get_role_permissions(conn, "Commerciale")
    assert comm_perms == {"00_Home", "01_Dashboard"}

    # Tentativo di cancellare Admin deve fallire
    ok_del_admin, _ = roles.delete_role(conn, "Admin")
    assert ok_del_admin is False

    # Cancellare Commerciale ha successo
    ok_del, _ = roles.delete_role(conn, "Commerciale")
    assert ok_del is True
    assert "Commerciale" not in [r["nome"] for r in roles.get_all_roles(conn)]


def test_user_role_assignment(conn):
    roles.init_roles(conn)

    # Primo utente diventa Admin automaticamente
    ruolo_primo = roles.get_user_role(conn, "primo.admin@azienda.com")
    assert ruolo_primo == "Admin"

    # Secondo utente non registrato riceve Finance
    ruolo_secondo = roles.get_user_role(conn, "secondo@azienda.com")
    assert ruolo_secondo == "Finance"

    # Assegnazione esplicita a Logistica
    ok, _ = roles.set_user_role(conn, "secondo@azienda.com", "Logistica")
    assert ok is True
    assert roles.get_user_role(conn, "secondo@azienda.com") == "Logistica"

    # Impossibile rimuovere l'unico Admin
    ok_del, msg = roles.delete_user_role(conn, "primo.admin@azienda.com")
    assert ok_del is False
    assert "unico amministratore" in msg.lower()
