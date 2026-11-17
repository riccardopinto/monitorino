"""Applicazione FastAPI. Avvio in sviluppo: ``uv run fastapi dev app/main.py``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import stato
from app.core import db
from app.core.config import RADICE, impostazioni

VERSIONE = "0.1.0"
DIR_WEB = RADICE / "web"


def crea_app(percorso_db: Path | None = None) -> FastAPI:
    """Costruisce l'app. ``percorso_db`` serve ai test; di default si usa DB_PATH da .env."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        con = db.connetti(percorso_db or impostazioni().db_path)
        db.crea_schema(con)
        app.state.db = con
        yield
        con.close()

    app = FastAPI(title="Monitorino", version=VERSIONE, lifespan=lifespan)
    app.include_router(stato.router)
    app.mount("/static", StaticFiles(directory=DIR_WEB / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(DIR_WEB / "index.html")

    return app


app = crea_app()
