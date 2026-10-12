"""Helper per la formattazione delle tabelle Streamlit (column_config), condivisi fra le pagine."""

from __future__ import annotations

import streamlit as st

from .formatting import etichetta_periodo


def guard_pipeline():
    """Ferma il rendering della pagina con un messaggio guida se la pipeline non è pronta."""
    pipe = st.session_state.get("pipeline")
    if pipe is None:
        st.info("Scegli periodo e perimetro nella barra in alto e premi **Applica**. "
                "Se il DB è vuoto, carica i file da **Export & Sistema → Carica Dati**.")
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


def period_labels(n: int = 2, lunghe: bool = False, fiscali: bool = False) -> list[str]:
    """Etichette dei periodi in confronto: l'anno dell'ULTIMA data del periodo scelto e i relativi -1 e -2
    (es. 01/11/2025 → 31/10/2026 ⇒ ["2026", "2025", "2024"]). Con `lunghe=True` (grafici) un periodo a
    cavallo d'anno diventa ["2025/26", "2024/25", "2023/24"]. Con `fiscali=True` (export) diventa ["25/26", "24/25", "23/24"].
    Fallback (nessun report ancora generato): le vecchie etichette di slot."""
    sel = st.session_state.get("sel_periodo_a")
    if isinstance(sel, (tuple, list)) and len(sel) == 2 and hasattr(sel[1], "year"):
        anni = [etichetta_periodo(sel[0], sel[1], i, lunga=lunghe, fiscale=fiscali) for i in range(3)]
        return anni[:n] + [f"Periodo {i + 1}" for i in range(3, n)]
    labels = ["Range selezionato", "Anno precedente", "Due anni precedenti"]
    return labels[:n] + [f"Periodo {i + 1}" for i in range(len(labels), n)]


def shift_year(d, years: int):
    """Sposta una data di N anni, gestendo il 29 febbraio su anno non bisestile."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)
