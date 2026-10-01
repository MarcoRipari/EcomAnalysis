"""Helper per la formattazione delle tabelle Streamlit (column_config), condivisi fra le pagine."""

from __future__ import annotations

import streamlit as st


def guard_pipeline():
    """Ferma il rendering della pagina con un messaggio guida se la pipeline non è pronta."""
    pipe = st.session_state.get("pipeline")
    if pipe is None:
        st.info("⬅️ Apri **⬆️ Carica Dati**, scegli periodo e perimetro e premi **Genera dati report** per usare questa pagina.")
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
    """Etichette-ANNO dei periodi in confronto: anno del periodo scelto (data FINALE)
    e i relativi -1 e -2. Es. scelto 01/01/2026 → 30/06/2026 ⇒ ["2026", "2025", "2024"].
    Fallback (nessun report ancora generato): le vecchie etichette di slot."""
    sel = st.session_state.get("sel_periodo_a")
    if isinstance(sel, (tuple, list)) and len(sel) == 2 and hasattr(sel[1], "year"):
        y = sel[1].year                       # anno della data finale del periodo scelto
        anni = [str(y), str(y - 1), str(y - 2)]
        return anni[:n] + [f"Periodo {i + 1}" for i in range(3, n)]
    labels = ["Range selezionato", "Anno precedente", "Due anni precedenti"]
    return labels[:n] + [f"Periodo {i + 1}" for i in range(len(labels), n)]


def shift_year(d, years: int):
    """Sposta una data di N anni, gestendo il 29 febbraio su anno non bisestile."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
