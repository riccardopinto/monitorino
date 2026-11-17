"""Classificazione dei documenti con la Message Batches API (quando c'è la chiave Anthropic).

Ogni richiesta del batch contiene fino a DOC_PER_RICHIESTA documenti; le istruzioni stanno
nel system prompt con cache_control, uguali per tutte le richieste. L'output è JSON con
schema (output_config.format) e si valida con pydantic prima di salvarlo.

Uso da riga di comando (``uv run python -m app.temi classifica``): a ogni esecuzione si
raccolgono i batch conclusi e se ne invia uno nuovo per i documenti non ancora classificati.
I batch in corso stanno in data/processed/batch_temi.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from app.core.config import impostazioni
from app.ingest._comune import DIR_PROCESSED
from app.llm import prompt_temi as pt
from app.llm.client import ClientLLM, ErroreLLM

MODULO = "temi"
DOC_PER_RICHIESTA = 20
TOKEN_INPUT_STIMATI_PER_DOC = 180
TOKEN_OUTPUT_STIMATI_PER_DOC = 80
FILE_STATO = DIR_PROCESSED / "batch_temi.json"


def _leggi_stato(percorso: Path) -> dict[str, list[int]]:
    return json.loads(percorso.read_text(encoding="utf-8")) if percorso.exists() else {}


def _scrivi_stato(percorso: Path, stato: dict[str, list[int]]) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(stato, indent=2), encoding="utf-8")


def parametri(documenti: list[dict]) -> dict:
    return {
        "max_tokens": 8000,
        "system": [
            {"type": "text", "text": pt.istruzioni(), "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": pt.formatta_documenti(documenti)}],
        # Classificazione semplice: poco ragionamento, output vincolato allo schema.
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": pt.schema_risposta()},
        },
    }


def raccogli_conclusi(
    con: duckdb.DuckDBPyConnection, client: ClientLLM, stato_file: Path = FILE_STATO
) -> dict[str, int]:
    stato = _leggi_stato(stato_file)
    applicati = errori = 0
    for batch_id in list(stato):
        if client.stato_batch(batch_id) != "ended":
            continue
        for _, msg in client.risultati_batch(
            batch_id, modulo=MODULO, ruolo="classificazione"
        ).items():
            if msg is None or msg.stop_reason == "refusal":
                errori += 1
                continue
            testo = next((b.text for b in msg.content if b.type == "text"), "")
            try:
                esito = pt.applica(con, pt.estrai_json(testo), origine="api")
            except (ValueError, json.JSONDecodeError):
                errori += 1
                continue
            applicati += len(esito["applicati"])
            errori += len(esito["errori"])
        del stato[batch_id]
    _scrivi_stato(stato_file, stato)
    return {"applicati": applicati, "errori": errori, "batch_in_corso": len(stato)}


def invia(
    con: duckdb.DuckDBPyConnection, client: ClientLLM, stato_file: Path = FILE_STATO
) -> dict[str, object]:
    stato = _leggi_stato(stato_file)
    in_corso = {i for ids in stato.values() for i in ids}
    documenti = pt.documenti_da_classificare(con, esclusi=in_corso)
    if not documenti:
        return {"inviati": 0}
    gruppi = [
        documenti[i : i + DOC_PER_RICHIESTA] for i in range(0, len(documenti), DOC_PER_RICHIESTA)
    ]
    richieste = [(f"gruppo-{n}", parametri(g)) for n, g in enumerate(gruppi)]
    previsto = client.stima_eur(
        "classificazione",
        TOKEN_INPUT_STIMATI_PER_DOC * len(documenti),
        TOKEN_OUTPUT_STIMATI_PER_DOC * len(documenti),
        batch=True,
    )
    batch_id = client.crea_batch(
        ruolo="classificazione", richieste=richieste, costo_previsto_eur=previsto
    )
    stato[batch_id] = [d["id"] for d in documenti]
    _scrivi_stato(stato_file, stato)
    return {"inviati": len(documenti), "batch": batch_id, "costo_previsto_eur": round(previsto, 4)}


def classifica(con: duckdb.DuckDBPyConnection, client: ClientLLM | None = None) -> dict:
    if client is None:
        if impostazioni().anthropic_api_key is None:
            raise ErroreLLM(
                "Chiave Anthropic assente: usare il flusso chat "
                "(`uv run python -m app.temi esporta`, poi `importa`)"
            )
        client = ClientLLM(con)
    return {"raccolti": raccogli_conclusi(con, client), "nuovo": invia(con, client)}
