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


def fmt_var(x, decimals: int = 1) -> str:
    """Variazione relativa con segno: +3,3% / -5,6% (— se non calcolabile, es. base zero)."""
    if _is_nan(x):
        return "—"
    s = f"{abs(x) * 100:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if x < 0 else '+'}{s}%"


def fmt_pp(x, decimals: int = 1) -> str:
    """Differenza in punti percentuali fra due percentuali (frazioni): +2,0 pp."""
    if _is_nan(x):
        return "—"
    s = f"{abs(x) * 100:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if x < 0 else '+'}{s} pp"


def etichetta_periodo(start, end, indietro: int = 0, lunga: bool = False) -> str:
    """Etichetta di un periodo spostato di `indietro` anni.

    Breve (tabelle, nomi di colonna): l'anno dell'ultima data del periodo, es. "2026" per 01/11/2025 →
    31/10/2026 e "2025" per il precedente.
    Lunga (grafici): "2025/26" se il periodo è a cavallo d'anno, così novembre 2025 non sembra 2026;
    uguale alla breve se il periodo sta in un solo anno solare."""
    y0, y1 = start.year - indietro, end.year - indietro
    if not lunga or y0 == y1:
        return str(y1)
    return f"{y0}/{str(y1)[-2:]}"


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
