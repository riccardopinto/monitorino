"""Istruzioni e formato della classificazione dei documenti per tema, sentiment e area.

Sono le stesse per i due flussi:
- API (app/llm/classificazione.py, Message Batches API);
- chat (app/temi/chat.py): il prompt si esporta, si incolla in una chat e il JSON della
  risposta si reimporta.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

import duckdb
from pydantic import BaseModel, Field, field_validator

from app.core.config import CIRCOSCRIZIONI, segmenti, temi

ALTRO = "altro"


def tassonomia() -> list[str]:
    return [*temi().temi, ALTRO]


class Classificazione(BaseModel):
    id: int
    pertinente: bool
    tema: str
    sentiment: int = Field(ge=-2, le=2)
    circoscrizione: str | None = None
    sintesi: str = Field(max_length=400)

    @field_validator("tema")
    @classmethod
    def _tema_valido(cls, v: str) -> str:
        if v not in tassonomia():
            raise ValueError(f"tema non previsto: {v!r}")
        return v

    @field_validator("circoscrizione", mode="before")
    @classmethod
    def _circ_valida(cls, v):
        if v in (None, "", "null"):
            return None
        v = str(v).strip()
        if v not in CIRCOSCRIZIONI:
            raise ValueError(f"circoscrizione non valida: {v!r}")
        return v


def schema_risposta() -> dict:
    """JSON schema della risposta (output strutturato dell'API e esempio per la chat)."""
    return {
        "type": "object",
        "properties": {
            "classificazioni": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "pertinente": {"type": "boolean"},
                        "tema": {"type": "string", "enum": tassonomia()},
                        "sentiment": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
                        "circoscrizione": {
                            "anyOf": [
                                {"type": "string", "enum": list(CIRCOSCRIZIONI)},
                                {"type": "null"},
                            ]
                        },
                        "sintesi": {"type": "string"},
                    },
                    "required": [
                        "id",
                        "pertinente",
                        "tema",
                        "sentiment",
                        "circoscrizione",
                        "sintesi",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classificazioni"],
        "additionalProperties": False,
    }


def istruzioni() -> str:
    """Istruzioni di sistema: stabili, così l'API può tenerle in cache."""
    elenco_temi = "\n".join(f"    * {t}" for t in tassonomia())
    circ = "\n".join(f"    * {k}: {v}" for k, v in segmenti().circoscrizioni.items())
    return f"""Classifichi notizie e contenuti pubblici sulla città di Torino per un'analisi \
aggregata dei temi discussi. Per ogni documento restituisci:

- id: l'id del documento, invariato.
- pertinente: true se il documento riguarda la città di Torino (anche un suo quartiere);
  false se riguarda solo altri comuni, la provincia, temi nazionali o esteri senza un legame
  diretto con la città.
- tema: uno solo, dalla lista seguente; se nessuno è adatto usa "{ALTRO}".
{elenco_temi}
- sentiment: il tono verso la situazione della città sul tema, da -2 (molto negativo:
  problema, protesta, disagio) a +2 (molto positivo: miglioramento, soluzione, successo);
  0 se neutro o informativo.
- circoscrizione: "1"…"8" solo se il testo indica chiaramente un luogo di quella
  circoscrizione; altrimenti null. Circoscrizioni:
{circ}
- sintesi: una frase neutra di massimo 25 parole sul contenuto, in italiano. Non riportare
  nomi di utenti social, citazioni testuali lunghe o dati personali.

Regole: classifica solo in base al testo fornito, non aggiungere fatti. Non giudicare le
persone citate. Rispondi solo con il JSON richiesto, un elemento per ogni documento."""


def documenti_da_classificare(
    con: duckdb.DuckDBPyConnection, limite: int | None = None, esclusi: set[int] | None = None
) -> list[dict]:
    righe = con.execute(
        "SELECT id, fonte, tipo_fonte, data, titolo, sintesi, testo FROM documento "
        "WHERE classificato_da IS NULL ORDER BY data DESC, id DESC"
    ).fetchall()
    out = []
    for id_, fonte, tipo, data, titolo, sintesi, testo in righe:
        if esclusi and id_ in esclusi:
            continue
        out.append(
            {
                "id": id_,
                "fonte": fonte,
                "tipo": tipo,
                "data": data.isoformat() if data else "",
                "titolo": titolo or "",
                "testo": (sintesi or testo or "")[:600],
            }
        )
        if limite and len(out) >= limite:
            break
    return out


def formatta_documenti(documenti: list[dict]) -> str:
    blocchi = []
    for d in documenti:
        righe = [f"[id {d['id']}] {d['fonte']} ({d['tipo']}), {d['data']}"]
        if d["titolo"]:
            righe.append(f"Titolo: {d['titolo']}")
        if d["testo"]:
            righe.append(f"Testo: {d['testo']}")
        blocchi.append("\n".join(righe))
    return "\n\n".join(blocchi)


def estrai_json(testo: str) -> list[dict]:
    """Legge la risposta: oggetto {"classificazioni": [...]} o lista, anche tra ```json ```."""
    t = testo.strip()
    if m := re.search(r"```(?:json)?\s*(.*?)```", t, re.S):
        t = m.group(1).strip()
    dati = json.loads(t)
    if isinstance(dati, dict):
        dati = dati.get("classificazioni", [])
    if not isinstance(dati, list):
        raise ValueError("Formato non riconosciuto: attesa una lista di classificazioni")
    return dati


def applica(con: duckdb.DuckDBPyConnection, voci: list[dict], origine: str) -> dict[str, list]:
    """Valida e salva le classificazioni. Non sovrascrive documenti già classificati.

    La circoscrizione del modello si usa solo se il dizionario dei luoghi non l'ha trovata;
    la sintesi del modello si salva solo dove manca (contenuti social).
    """
    esito: dict[str, list] = {
        "applicati": [],
        "errori": [],
        "sconosciuti": [],
        "gia_classificati": [],
    }
    ids = dict(con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall())
    adesso = datetime.now()
    for voce in voci:
        try:
            c = Classificazione.model_validate(voce)
        except Exception as e:  # noqa: BLE001 - si raccoglie e si riporta
            esito["errori"].append({"voce": voce, "errore": str(e)[:200]})
            continue
        riga = con.execute(
            "SELECT classificato_da, area_id FROM documento WHERE id = ?", [c.id]
        ).fetchone()
        if riga is None:
            esito["sconosciuti"].append(c.id)
            continue
        if riga[0] is not None:
            esito["gia_classificati"].append(c.id)
            continue
        area = (
            riga[1]
            if riga[1] is not None
            else (ids.get(c.circoscrizione) if c.circoscrizione else None)
        )
        con.execute(
            "UPDATE documento SET tema = ?, sentiment = ?, pertinente = ?, area_id = ?, "
            "sintesi = coalesce(sintesi, ?), classificato_da = ?, classificato_il = ? WHERE id = ?",
            [c.tema, c.sentiment, c.pertinente, area, c.sintesi, origine, adesso, c.id],
        )
        esito["applicati"].append(c.id)
    return esito
