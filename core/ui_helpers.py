"""Helper per la formattazione delle tabelle Streamlit (column_config), condivisi fra le pagine."""

from __future__ import annotations

import streamlit as st


def guard_pipeline():
    """Ferma il rendering della pagina con un messaggio guida se la pipeline non è pronta."""
    pipe = st.session_state.get("pipeline")
    if pipe is None:
        st.info("⬅️ Carica i dati e premi **Genera dati report** nella home per usare questa pagina.")
        st.stop()
    return pipe


def currency_col(label: str | None = None):
    return st.column_config.NumberColumn(label, format="€ %.2f")


def percent_col(label: str | None = None):
    return st.column_config.NumberColumn(label, format="percent")


def number_col(label: str | None = None):
    return st.column_config.NumberColumn(label, format="%.0f")


def image_col(label: str = "Foto"):
    return st.column_config.ImageColumn(label)


def period_labels(n: int = 2) -> list[str]:
    """Etichette dei periodi in comparazione, legate allo SLOT (corrente/precedente/...) e non
    all'anno solare corrente — prima usavano datetime.date.today().year, disallineate dal
    range di date effettivamente selezionato in home."""
    labels = ["Range selezionato", "Anno precedente", "Due anni precedenti"]
    return labels[:n] + [f"Periodo {i+1}" for i in range(len(labels), n)]


def shift_year(d, years: int):
    """Sposta una data di N anni, gestendo il 29 febbraio su anno non bisestile."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
