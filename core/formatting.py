"""
Formattazione a stringa (stile italiano: punto separatore migliaia, virgola decimale) per le
tabelle "miste" dove righe diverse rappresentano metriche di tipo diverso (valuta, percentuale,
conteggio) nella STESSA colonna — es. una tabella KPI con righe "Fatturato"/"Ordini"/"% Reso" e
colonne "Range selezionato"/"Anno precedente". In questi casi il column_config di Streamlit non
basta: si applica a livello di COLONNA, non di singola cella, quindi non può formattare la stessa
colonna in modo diverso riga per riga. Qui costruiamo direttamente la stringa già formattata.

Per le tabelle "larghe" (una riga = un'entità, colonne = metriche omogenee per tipo, es. la
tabella comparativa marketplace) si continua invece a usare core.ui_helpers.currency_col/
percent_col/number_col via column_config, che lì funziona correttamente e mantiene i valori
numerici ordinabili nella UI interattiva di Streamlit.
"""

from __future__ import annotations

import math


def _is_nan(x) -> bool:
    try:
        return x is None or (isinstance(x, float) and math.isnan(x))
    except TypeError:
        return False


def fmt_currency(x) -> str:
    if _is_nan(x):
        return "—"
    segno = "-" if x < 0 else ""
    s = f"{abs(x):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{segno}€ {s}"


def fmt_percent(x, decimals: int = 1) -> str:
    if _is_nan(x):
        return "—"
    s = f"{x * 100:,.{decimals}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s}%"


def fmt_number(x, decimals: int = 0) -> str:
    if _is_nan(x):
        return "—"
    s = f"{x:,.{decimals}f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


# Tipo -> formattatore, usato dalle tabelle "miste" (kpi_block, nazioni_kpi_table)
FORMATTERS = {
    "currency": fmt_currency,
    "percent": fmt_percent,
    "number": fmt_number,
}


def fmt(x, kind: str) -> str:
    return FORMATTERS[kind](x)
