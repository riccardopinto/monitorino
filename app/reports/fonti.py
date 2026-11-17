"""Fonti e date dei dati per la sezione finale dei report.

Le date vengono dalla tabella ``caricamento`` (ultimo caricamento riuscito di ogni fonte);
URL, licenze e formati sono in docs/fonti_dati.md.
"""

from __future__ import annotations

import duckdb

# chiave di caricamento (o prefisso con "*") -> (dato, fonte)
CATALOGO: dict[str, tuple[str, str]] = {
    "comune_circoscrizioni": ("Confini delle circoscrizioni", "Comune di Torino, geoportale"),
    "comune_seggi": (
        "Corrispondenza indirizzi–sezioni elettorali",
        "Comune di Torino, open data",
    ),
    "comune_civici": (
        "Numerazione civica (per i confini approssimati delle sezioni)",
        "Comune di Torino, open data",
    ),
    "elezioni:*": ("Risultati elettorali per sezione", "Comune di Torino, Ufficio elettorale"),
    "eligendo": ("Totali ufficiali di controllo", "Ministero dell'Interno, Eligendo"),
    "comune_demografia": (
        "Popolazione per circoscrizione, età, sesso, cittadinanza",
        "Comune di Torino, Ufficio di statistica",
    ),
    "istat_censimento_2021": (
        "Istruzione, occupazione, famiglie per sezione di censimento",
        "ISTAT, Censimento permanente 2021",
    ),
    "mef_redditi": ("Redditi IRPEF per CAP", "MEF - Dipartimento delle Finanze"),
    "news": ("Notizie locali e comunicati (titoli e sommari)", "Feed RSS delle testate locali"),
    "social": ("Contenuti social pubblici (solo conteggi aggregati)", "API ufficiali"),
}

PER_REPORT: dict[str, list[str]] = {
    "scheda": ["comune_circoscrizioni", "elezioni:*", "eligendo", "comune_demografia",
               "istat_censimento_2021", "mef_redditi", "news"],
    "confronto": ["comune_circoscrizioni", "elezioni:*", "eligendo", "comune_demografia",
                  "istat_censimento_2021", "mef_redditi"],
    "bollettino": ["comune_circoscrizioni", "news", "social"],
    "simulazione": ["comune_circoscrizioni", "elezioni:*", "comune_demografia",
                    "istat_censimento_2021", "news"],
    "kit": [],
}  # fmt: skip


def elenco(con: duckdb.DuckDBPyConnection, chiavi: list[str]) -> list[dict]:
    """Righe {dato, fonte, aggiornato, dettaglio} per le fonti indicate."""
    out = []
    for chiave in chiavi:
        dato, fonte = CATALOGO[chiave]
        if chiave.endswith("*"):
            righe = con.execute(
                "SELECT fonte, max(timestamp) FROM caricamento WHERE fonte LIKE ? "
                "GROUP BY 1 ORDER BY 1",
                [chiave[:-1] + "%"],
            ).fetchall()
            if not righe:
                continue
            consultazioni = ", ".join(f.split(":", 1)[1] for f, _ in righe)
            ultima = max(t for _, t in righe)
            out.append({"dato": dato, "fonte": fonte, "aggiornato": ultima.date().isoformat(),
                        "dettaglio": consultazioni})  # fmt: skip
            continue
        (ultima,) = con.execute(
            "SELECT max(timestamp) FROM caricamento WHERE fonte = ?", [chiave]
        ).fetchone()
        if ultima is None:
            continue
        out.append({"dato": dato, "fonte": fonte, "aggiornato": ultima.date().isoformat(),
                    "dettaglio": ""})  # fmt: skip
    return out
