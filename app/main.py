"""Applicazione FastAPI. Avvio in sviluppo: ``uv run fastapi dev app/main.py``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import aree, demografia, elezioni, laboratorio, report, stato, temi
from app.core import db
from app.core.config import RADICE, impostazioni

VERSIONE = "0.1.0"
DIR_WEB = RADICE / "web"


def crea_app(
    percorso_db: Path | None = None,
    mappa_sfondo: str | None = None,
    cartella_report: Path | None = None,
) -> FastAPI:
    """Costruisce l'app.

    I parametri servono ai test: di default si usano DB_PATH e MAPPA_SFONDO da .env.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        automatica = False
        if percorso_db is None:
            imp = impostazioni()
            percorso, sfondo = imp.db_path, mappa_sfondo or imp.mappa_sfondo
            automatica = imp.raccolta_automatica
        else:
            percorso, sfondo = percorso_db, mappa_sfondo or "nessuna"
        con = db.connetti(percorso)
        db.crea_schema(con)
        app.state.db = con
        app.state.mappa_sfondo = sfondo
        app.state.cache_aree = {}
        app.state.cache_elezioni = {}
        app.state.cartella_report = cartella_report
        pianificatore = None
        if automatica:
            from app.temi import pianificatore as pt

            pianificatore = pt.avvia(con)
        yield
        if pianificatore:
            pianificatore.shutdown(wait=False)
        con.close()

    app = FastAPI(title="Monitorino", version=VERSIONE, lifespan=lifespan)
    app.include_router(stato.router)
    app.include_router(aree.router)
    app.include_router(elezioni.router)
    app.include_router(demografia.router)
    app.include_router(temi.router)
    app.include_router(laboratorio.router)
    app.include_router(report.router)
    app.mount("/static", StaticFiles(directory=DIR_WEB / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(DIR_WEB / "index.html")

    return app


app = crea_app()
