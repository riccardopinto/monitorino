"""API dei report PDF: anteprima HTML, generazione, archivio e download."""

from __future__ import annotations

import json
from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.api.dipendenze import cursore
from app.core.config import elenco_candidati
from app.reports import dati, genera

router = APIRouter(prefix="/api/report", tags=["report"])
Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]


class RichiestaReport(BaseModel):
    tipo: str
    parametri: dict = Field(default_factory=dict)
    titolo: str = Field(default="", max_length=200)
    autore: str = Field(default="", max_length=100)


def _contesto(con, request: Request, r: RichiestaReport) -> dict:
    try:
        return dati.contesto(con, r.tipo, r.parametri, autore=r.autore.strip(),
                             titolo=r.titolo.strip(), versione=request.app.version)  # fmt: skip
    except dati.ErroreDati as e:
        raise HTTPException(422, str(e)) from e
    except HTTPException as e:
        raise HTTPException(e.status_code, f"Dati non disponibili: {e.detail}") from e
    except ValueError as e:
        raise HTTPException(422, f"Parametri non validi: {e}") from e


def _cartella(request: Request):
    return getattr(request.app.state, "cartella_report", None) or genera.DIR_USCITA


@router.get("/tipi")
def tipi(con: Con) -> dict:
    elezioni = con.execute(
        "SELECT id, nome, data FROM elezione ORDER BY data, tipo, turno"
    ).fetchall()
    simulazioni = con.execute(
        "SELECT id, proposta FROM simulazione WHERE stato = 'completata' ORDER BY id DESC LIMIT 100"
    ).fetchall()
    (settimana,) = con.execute("SELECT max(settimana) FROM tema_aggregato").fetchone()
    circoscrizioni = con.execute(
        "SELECT codice, nome FROM area WHERE tipo = 'circoscrizione' "
        "ORDER BY try_cast(codice AS INTEGER), codice"
    ).fetchall()
    return {
        "tipi": dati.TIPI,
        "elezioni": [{"id": i, "nome": n, "data": d.isoformat()} for i, n, d in elezioni],
        "simulazioni": [{"id": i, "proposta": p} for i, p in simulazioni],
        "candidati": [{"chiave": k, "nome": c.nome} for k, c in elenco_candidati()],
        "circoscrizioni": [{"codice": c, "nome": n} for c, n in circoscrizioni],
        "ultima_settimana": settimana.isoformat() if settimana else None,
    }


@router.post("/anteprima", response_class=HTMLResponse)
def anteprima(con: Con, request: Request, r: RichiestaReport) -> HTMLResponse:
    """HTML del report, identico a quello che va in stampa."""
    return HTMLResponse(genera.html(r.tipo, _contesto(con, request, r)))


@router.post("")
def crea(con: Con, request: Request, r: RichiestaReport) -> dict:
    ctx = _contesto(con, request, r)
    try:
        pdf = genera.stampa(genera.html(r.tipo, ctx), ctx)
    except genera.ErroreReport as e:
        raise HTTPException(503, str(e)) from e
    esito = genera.archivia(
        con,
        tipo=r.tipo,
        titolo=ctx["titolo"],
        parametri=r.parametri,
        autore=r.autore.strip(),
        pdf=pdf,
        cartella=_cartella(request),
    )
    return {**esito, "titolo": ctx["titolo"], "url": f"/api/report/{esito['id']}/pdf"}


@router.get("")
def archivio(con: Con) -> dict:
    righe = con.execute(
        "SELECT id, tipo, titolo, parametri, autore, timestamp, file, pagine, durata_s, browser "
        "FROM report ORDER BY id DESC LIMIT 300"
    ).fetchall()
    return {
        "report": [
            {"id": i, "tipo": t, "etichetta_tipo": dati.TIPI.get(t, t), "titolo": ti,
             "parametri": json.loads(p) if p else {}, "autore": a,
             "timestamp": ts.isoformat(timespec="minutes"), "file": f, "pagine": pg,
             "durata_s": d, "browser": b, "url": f"/api/report/{i}/pdf"}
            for i, t, ti, p, a, ts, f, pg, d, b in righe
        ]
    }  # fmt: skip


@router.get("/{rid}/pdf")
def scarica(con: Con, request: Request, rid: int) -> FileResponse:
    riga = con.execute("SELECT file FROM report WHERE id = ?", [rid]).fetchone()
    if not riga or not riga[0]:
        raise HTTPException(404, f"Report {rid} non trovato")
    percorso = _cartella(request) / riga[0]
    if not percorso.is_file():
        raise HTTPException(410, "Il file del report non è più presente in reports_out/")
    return FileResponse(percorso, media_type="application/pdf", filename=riga[0])
