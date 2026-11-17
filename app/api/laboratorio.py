"""API del laboratorio messaggi. Ogni risposta con risultati porta la dicitura obbligatoria."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal

import duckdb
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.analysis import calibrazione as cal
from app.api.dipendenze import cursore
from app.core.config import elenco_candidati, impostazioni, segmenti
from app.llm import contesto as ctx
from app.llm import prompt_simulazione as ps
from app.llm import simulazione as sim
from app.llm.client import ClientLLM, ErroreLLM, TettoSpesaSuperato

router = APIRouter(prefix="/api/laboratorio", tags=["laboratorio"])
Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]
AVVERTENZE = {"dicitura": ps.DICITURA, "limiti": list(ps.LIMITI)}


def api_disponibile() -> bool:
    return impostazioni().anthropic_api_key is not None


def client_llm(request: Request) -> ClientLLM:
    """Sostituibile nei test con ``app.dependency_overrides``."""
    if not api_disponibile():
        raise HTTPException(409, "Chiave API Anthropic non configurata: usare il flusso chat")
    return ClientLLM(request.app.state.db.cursor())


Client = Annotated[ClientLLM, Depends(client_llm)]


def _md(testo: str, nome: str) -> PlainTextResponse:
    return PlainTextResponse(
        testo,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def _carica(con, sid: int) -> dict:
    try:
        return sim.carica(con, sid)
    except sim.ErroreSimulazione as e:
        raise HTTPException(404, str(e)) from e


# --- opzioni ----------------------------------------------------------------


@router.get("/opzioni")
def opzioni(con: Con) -> dict:
    seg = segmenti()
    candidati = [
        {"chiave": k, "nome": c.nome, "ruolo": c.ruolo, "lista": c.lista,
         "elettorato_potenziale": c.elettorato_potenziale,
         "segmenti_elettorato": ctx.segmenti_elettorato(c)}
        for k, c in elenco_candidati()
    ]  # fmt: skip
    return {
        **AVVERTENZE,
        "candidati": candidati,
        "circoscrizioni": [{"codice": k, "nome": v} for k, v in sorted(seg.circoscrizioni.items())],
        "fasce_eta": seg.fasce_eta,
        "condizioni": seg.condizione,
        "aree_di_voto": seg.area_di_voto,
        "segmenti_predefiniti": ctx.segmenti_predefiniti(),
        "persone_per_segmento": seg.persone_per_segmento,
        "varianti_pesi": list(seg.pesi_voto.varianti),
        "variante_attiva": seg.pesi_voto.attiva,
        "api_disponibile": api_disponibile(),
        "metriche_calibrazione": cal.METRICHE,
        "segmenti_per_blocco": sim.SEGMENTI_PER_BLOCCO,
    }


# --- simulazioni ------------------------------------------------------------


class NuovaSimulazione(BaseModel):
    proposta: str = Field(min_length=3, max_length=4000)
    proposta_b: str | None = Field(default=None, max_length=4000)
    candidato: str
    aree: list[str] = Field(min_length=1)
    segmenti: list[dict] = Field(min_length=1, max_length=120)
    persone: int = Field(default=10, ge=1, le=30)
    variante: str = "comunali"
    seed: int = Field(default=1, ge=0)
    origine: Literal["chat", "api"] = "chat"
    note: str = ""


def _vista(run: dict) -> dict:
    """Run per l'interfaccia: senza panel e risposte grezze."""
    p = run["parametri"]
    try:
        stima = sim.stima(run) if run["origine"] == "api" else None
    except sim.ErroreSimulazione:
        stima = None
    return {
        **AVVERTENZE,
        "id": run["id"],
        "timestamp": run["timestamp"].isoformat(timespec="minutes"),
        "proposta": run["proposta"],
        "proposta_b": p.get("proposta_b"),
        "candidato": run["candidato"],
        "candidato_nome": p.get("candidato_nome"),
        "aree": run["aree"],
        "segmenti": run["segmenti"],
        "persone_per_segmento": p["persone_per_segmento"],
        "variante_pesi": run["variante_pesi"],
        "seed": run["seed"],
        "modello": run["modello"],
        "origine": run["origine"],
        "stato": run["stato"],
        "costo_eur": round(run["costo"] or 0, 4),
        "stima": stima,
        "versione_metodo": p.get("versione_metodo"),
        "temperatura": p.get("temperatura"),
        "blocchi": [{**b, "completato": b["n"] in p["blocchi_completati"]} for b in p["blocchi"]],
        "batch": p.get("batch"),
        "errori": run["risultati"].get("errori", []),
        "aggregati": run["risultati"].get("aggregati"),
        "sintesi": run["risultati"].get("sintesi"),
    }


@router.post("/simulazioni")
def crea(con: Con, corpo: NuovaSimulazione) -> dict:
    if corpo.origine == "api" and not api_disponibile():
        raise HTTPException(409, "Chiave API Anthropic non configurata: usare il flusso chat")
    try:
        sid = sim.crea(con, sim.Richiesta(**corpo.model_dump(exclude={"origine"})), corpo.origine)
    except (sim.ErroreSimulazione, KeyError, ValueError) as e:
        raise HTTPException(422, str(e).strip("'\"")) from e
    return _vista(sim.carica(con, sid))


@router.get("/simulazioni")
def archivio(con: Con) -> dict:
    righe = con.execute(
        "SELECT id, timestamp, proposta, candidato, aree, segmenti, stato, origine, costo, "
        "risultati->'$.aggregati.a.totale' FROM simulazione ORDER BY id DESC LIMIT 200"
    ).fetchall()
    out = []
    for sid, ts, proposta, cand, aree, segs, stato, origine, costo, totale in righe:
        out.append({
            "id": sid, "timestamp": ts.isoformat(timespec="minutes"), "proposta": proposta,
            "candidato": cand, "aree": json.loads(aree or "[]"),
            "n_segmenti": len(json.loads(segs or "[]")), "stato": stato, "origine": origine,
            "costo_eur": round(costo or 0, 4), "totale": json.loads(totale) if totale else None,
        })  # fmt: skip
    return {**AVVERTENZE, "simulazioni": out}


@router.get("/simulazioni/{sid}")
def dettaglio(con: Con, sid: int) -> dict:
    return _vista(_carica(con, sid))


@router.get("/simulazioni/{sid}/prompt/{n}", response_class=PlainTextResponse)
def prompt_blocco(con: Con, sid: int, n: int):
    run = _carica(con, sid)
    try:
        testo = sim.prompt_chat(run, n)
    except sim.ErroreSimulazione as e:
        raise HTTPException(404, str(e)) from e
    return _md(testo, f"simulazione_{sid}_blocco_{n}.md")


@router.post("/simulazioni/{sid}/risposte/{n}")
def importa_risposta(
    con: Con, sid: int, n: int, testo: Annotated[str, Body(media_type="text/plain")]
) -> dict:
    _carica(con, sid)
    try:
        esito = sim.importa_chat(con, sid, n, testo)
    except sim.ErroreSimulazione as e:
        raise HTTPException(422, str(e)) from e
    return {**esito, "simulazione": _vista(sim.carica(con, sid))}


@router.post("/simulazioni/{sid}/avvia")
def avvia(con: Con, client: Client, sid: int, conferma: bool = False) -> dict:
    run = _carica(con, sid)
    if run["origine"] != "api":
        raise HTTPException(409, "Simulazione creata per il flusso chat")
    if run["stato"] == "completata":
        raise HTTPException(409, "Simulazione già completata")
    try:
        esito = sim.esegui_api(con, sid, client, conferma=conferma)
    except sim.RichiestaConferma as e:
        raise HTTPException(
            409, {"messaggio": str(e), "conferma_richiesta": True, "costo_eur": e.costo}
        ) from e
    except TettoSpesaSuperato as e:
        raise HTTPException(403, str(e)) from e
    except ErroreLLM as e:
        raise HTTPException(502, str(e)) from e
    return {**esito, "simulazione": _vista(sim.carica(con, sid))}


@router.post("/simulazioni/{sid}/batch")
def aggiorna_batch(con: Con, client: Client, sid: int) -> dict:
    _carica(con, sid)
    try:
        esito = sim.raccogli_batch(con, sid, client)
    except sim.ErroreSimulazione as e:
        raise HTTPException(409, str(e)) from e
    except ErroreLLM as e:
        raise HTTPException(502, str(e)) from e
    return {**esito, "simulazione": _vista(sim.carica(con, sid))}


@router.get("/simulazioni/{sid}/prompt-sintesi", response_class=PlainTextResponse)
def prompt_sintesi(con: Con, sid: int):
    try:
        testo = sim.prompt_sintesi(_carica(con, sid))
    except sim.ErroreSimulazione as e:
        raise HTTPException(409, str(e)) from e
    return _md(testo, f"simulazione_{sid}_sintesi.md")


@router.post("/simulazioni/{sid}/sintesi")
def importa_sintesi(
    con: Con, sid: int, testo: Annotated[str, Body(media_type="text/plain")]
) -> dict:
    _carica(con, sid)
    if not testo.strip():
        raise HTTPException(422, "Sintesi vuota")
    try:
        sim.importa_sintesi(con, sid, testo)
    except sim.ErroreSimulazione as e:
        raise HTTPException(409, str(e)) from e
    return _vista(sim.carica(con, sid))


@router.post("/simulazioni/{sid}/sintesi-api")
def sintesi_api(con: Con, client: Client, sid: int) -> dict:
    _carica(con, sid)
    try:
        sim.genera_sintesi_api(con, sid, client)
    except sim.ErroreSimulazione as e:
        raise HTTPException(409, str(e)) from e
    except TettoSpesaSuperato as e:
        raise HTTPException(403, str(e)) from e
    except ErroreLLM as e:
        raise HTTPException(502, str(e)) from e
    return _vista(sim.carica(con, sid))


# --- calibrazione -----------------------------------------------------------


class NuovaCalibrazione(BaseModel):
    simulazione_id: int
    fonte_sondaggio: str = Field(min_length=2, max_length=300)
    metrica: str
    valore_reale: float
    data_sondaggio: date | None = None
    variante: Literal["a", "b"] = "a"
    area: str | None = None


@router.post("/calibrazioni")
def nuova_calibrazione(con: Con, corpo: NuovaCalibrazione) -> dict:
    try:
        esito = cal.registra(con, **corpo.model_dump())
    except cal.ErroreCalibrazione as e:
        raise HTTPException(422, str(e)) from e
    return {**esito, "affidabilita": cal.affidabilita(con)}


@router.get("/calibrazioni")
def calibrazioni(con: Con, simulazione_id: int | None = None) -> dict:
    return {"calibrazioni": cal.elenco(con, simulazione_id)}


@router.get("/affidabilita")
def affidabilita(con: Con) -> dict:
    return {**AVVERTENZE, **cal.affidabilita(con)}
