"""Raccolta automatica dentro l'app (APScheduler), attiva con RACCOLTA_AUTOMATICA=true.

Usa la connessione dell'app: con l'app accesa nessun altro processo può scrivere sul
database. Ogni job è anche un comando: ``uv run python -m app.temi tutto``.
"""

from __future__ import annotations

import logging

import duckdb
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("monitorino.temi")
ORA_RACCOLTA = 6


def _job(con: duckdb.DuckDBPyConnection) -> None:
    from app.temi.__main__ import esegui_raccolta

    try:
        with con.cursor() as cur:
            esito = esegui_raccolta(cur)
        log.info("Raccolta temi completata: %s", esito)
    except Exception:  # noqa: BLE001 - un errore non deve fermare il pianificatore
        log.exception("Raccolta temi fallita")


def avvia(con: duckdb.DuckDBPyConnection) -> BackgroundScheduler:
    pianificatore = BackgroundScheduler(timezone="Europe/Rome")
    pianificatore.add_job(
        _job, "cron", hour=ORA_RACCOLTA, minute=0, args=[con], id="raccolta_temi",
        replace_existing=True, misfire_grace_time=3600, coalesce=True,
    )  # fmt: skip
    pianificatore.start()
    return pianificatore
