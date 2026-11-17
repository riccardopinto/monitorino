"""Stato dell'applicazione: usato dall'interfaccia per l'etichetta "DATI DI PROVA"."""

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.dipendenze import cursore
from app.core import db

router = APIRouter(prefix="/api", tags=["stato"])


class Stato(BaseModel):
    versione: str
    schema_completo: bool
    dati_di_prova: bool


@router.get("/stato")
def leggi_stato(
    request: Request, con: Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]
) -> Stato:
    return Stato(
        versione=request.app.version,
        schema_completo=db.schema_completo(con),
        dati_di_prova=db.dati_di_prova(con),
    )
