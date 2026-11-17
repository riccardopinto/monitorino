"""Normalizzazione dei codici di sezione elettorale e circoscrizione.

Regola (documentata in docs/fonti_dati.md):
- circoscrizione: stringa "1"–"8", senza zeri iniziali né prefissi;
- sezione: numero intero positivo in stringa, senza zeri iniziali né spazi.
Ogni script di ingest passa i codici da queste funzioni prima di scrivere in DuckDB.
"""

from __future__ import annotations

import re

_ROMANI = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}
_PREFISSO_CIRC = re.compile(r"^(circoscrizione|circ\.?)\s*", re.IGNORECASE)
_INTERO_DECIMALE = re.compile(r"^(\d+)(\.0+)?$")


def _intero(testo: str) -> int | None:
    trovato = _INTERO_DECIMALE.match(testo)
    return int(trovato.group(1)) if trovato else None


def normalizza_sezione(valore: str | int | float) -> str:
    """'0123', ' 123 ', 123, 123.0 -> '123'."""
    testo = str(valore).strip().replace(" ", "")
    numero = _intero(testo)
    if numero is None or numero <= 0:
        raise ValueError(f"codice di sezione non valido: {valore!r}")
    return str(numero)


def normalizza_circoscrizione(valore: str | int | float) -> str:
    """'03', 3, 'Circoscrizione 3', 'Circ. III', 'iii' -> '3'."""
    testo = _PREFISSO_CIRC.sub("", str(valore).strip()).strip()
    numero = _intero(testo)
    if numero is None:
        numero = _ROMANI.get(testo.lower())
    if numero is None or not 1 <= numero <= 8:
        raise ValueError(f"codice di circoscrizione non valido: {valore!r}")
    return str(numero)
