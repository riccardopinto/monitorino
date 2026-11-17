"""Funzioni condivise dagli script di ingest."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import httpx

from app.core.config import RADICE

DIR_RAW = RADICE / "data" / "raw"
DIR_PROCESSED = RADICE / "data" / "processed"
USER_AGENT = "monitorino-ingest/0.1"


def scarica(url: str, fonte: str, *, giorno: date | None = None, dir_raw: Path = DIR_RAW) -> Path:
    """Scarica ``url`` in ``data/raw/<fonte>/<AAAA-MM-GG>/``.

    Se il file del giorno esiste già non lo riscarica: rieseguire l'ingest nello stesso
    giorno lavora sugli stessi originali. I file in data/raw non si modificano mai.
    """
    giorno = giorno or date.today()
    cartella = dir_raw / fonte / giorno.isoformat()
    destinazione = cartella / Path(urlparse(url).path).name
    if destinazione.exists() and destinazione.stat().st_size > 0:
        return destinazione
    cartella.mkdir(parents=True, exist_ok=True)
    temporaneo = destinazione.with_suffix(destinazione.suffix + ".parziale")
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=120, headers={"User-Agent": USER_AGENT}
    ) as risposta:
        risposta.raise_for_status()
        with temporaneo.open("wb") as f:
            for blocco in risposta.iter_bytes():
                f.write(blocco)
    temporaneo.replace(destinazione)
    return destinazione


def registra_caricamento(
    con: duckdb.DuckDBPyConnection, fonte: str, righe: int, *, di_prova: bool = False
) -> None:
    con.execute(
        "INSERT INTO caricamento (fonte, righe, di_prova) VALUES (?, ?, ?)",
        [fonte, righe, di_prova],
    )
