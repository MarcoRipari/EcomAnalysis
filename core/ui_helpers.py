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


def years():
    """Anno corrente / anno precedente, come new Date().getFullYear() nell'originale."""
    import datetime
    y = datetime.date.today().year
    return y, y - 1
