"""Prompt e schemi del laboratorio messaggi (stessi testi per API e chat)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.persone import PersonaSintetica

VERSIONE_METODO = "2026-11-fase5"
DICITURA = "Simulazione IA, non è un sondaggio"
EFFETTI = ("allontana", "nessuno", "avvicina")


def istruzioni() -> str:
    """Istruzioni di sistema: stabili tra tutte le chiamate (in cache via API)."""
    return """Simuli le reazioni di elettori sintetici di Torino a una proposta politica, per \
aiutare uno staff di campagna a scrivere messaggi migliori. Non è un sondaggio: è un esercizio \
per far emergere reazioni plausibili, timori e parole che restano in mente.

Per ogni persona del panel immagina come reagirebbe, coerentemente con il suo profilo (età, \
condizione, area di voto abituale, quartiere, tratti) e con il contesto della sua zona. Poi \
restituisci per ognuna:
- gradimento: da 1 (per nulla d'accordo) a 5 (molto d'accordo);
- effetto_voto: "allontana", "nessuno" o "avvicina", rispetto alla possibilità di votare il \
candidato che presenta la proposta;
- timori: fino a 3 preoccupazioni brevi (poche parole ciascuna); lista vuota se non ne ha;
- parole_ricordate: fino a 3 parole o espressioni della proposta che le resterebbero in mente;
- reazione: una frase in prima persona, come la direbbe quella persona (massimo 30 parole).

Regole:
- Sii realistico e non attenuare: chi per profilo sarebbe ostile, indifferente o diffidente \
deve risultarlo. Molti elettori non cambiano voto per una singola proposta: "nessuno" è spesso \
la risposta più verosimile. Chi di solito non vota tende a restare distante.
- Le persone dello stesso segmento non devono essere identiche: varia secondo i loro tratti.
- Non inventare fatti sulla proposta o sul candidato oltre a quanto scritto. Non attribuire \
dichiarazioni a persone reali.
- Rispondi solo con il JSON richiesto."""


def descrizione_segmento(s: dict) -> str:
    voto = s["area_di_voto"]
    abitudine = (
        "di solito non vanno a votare"
        if voto.startswith("astensione")
        else f"di solito votano {voto}"
    )
    return f"età {s['fascia_eta']}, {s['condizione']}, {abitudine}"


def testo_proposta(proposta: str, proposta_b: str | None, candidato: str) -> str:
    righe = [
        f"Candidato che presenta la proposta:\n{candidato}",
        f"Proposta A:\n{proposta.strip()}",
    ]
    if proposta_b:
        righe.append(
            f"Proposta B (stessa idea, formulata diversamente):\n{proposta_b.strip()}\n"
            "Ogni persona valuta sia A sia B, in modo indipendente."
        )
    return "\n\n".join(righe)


def testo_panel(persone: list[PersonaSintetica]) -> str:
    return "\n".join(p.descrizione() for p in persone)


# --- schemi -----------------------------------------------------------------


class Valutazione(BaseModel):
    gradimento: int = Field(ge=1, le=5)
    effetto_voto: Literal["allontana", "nessuno", "avvicina"]
    timori: list[str] = Field(default_factory=list, max_length=3)
    parole_ricordate: list[str] = Field(default_factory=list, max_length=3)
    reazione: str = Field(max_length=400)


class RispostaPersona(BaseModel):
    codice: str
    a: Valutazione
    b: Valutazione | None = None


class RispostaSegmento(BaseModel):
    indice: int  # posizione del segmento nel run
    persone: list[RispostaPersona]


def schema_valutazione() -> dict:
    return {
        "type": "object",
        "properties": {
            "gradimento": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "effetto_voto": {"type": "string", "enum": list(EFFETTI)},
            "timori": {"type": "array", "items": {"type": "string"}},
            "parole_ricordate": {"type": "array", "items": {"type": "string"}},
            "reazione": {"type": "string"},
        },
        "required": ["gradimento", "effetto_voto", "timori", "parole_ricordate", "reazione"],
        "additionalProperties": False,
    }


def schema_persone(con_b: bool) -> dict:
    proprieta = {"codice": {"type": "string"}, "a": schema_valutazione()}
    richiesti = ["codice", "a"]
    if con_b:
        proprieta["b"] = schema_valutazione()
        richiesti.append("b")
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": proprieta,
            "required": richiesti,
            "additionalProperties": False,
        },
    }


def schema_risposta_api(con_b: bool) -> dict:
    """Una chiamata = un segmento."""
    return {
        "type": "object",
        "properties": {"persone": schema_persone(con_b)},
        "required": ["persone"],
        "additionalProperties": False,
    }


def schema_risposta_chat(con_b: bool) -> dict:
    """Un prompt in chat = più segmenti della stessa area."""
    return {
        "type": "object",
        "properties": {
            "segmenti": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"indice": {"type": "integer"}, "persone": schema_persone(con_b)},
                    "required": ["indice", "persone"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["segmenti"],
        "additionalProperties": False,
    }


class ErroreRisposta(ValueError):
    pass


def valida(
    risposta: RispostaSegmento, panel: list[PersonaSintetica], con_b: bool
) -> RispostaSegmento:
    """Controlla che la risposta copra esattamente il panel e abbia B se richiesto."""
    attesi = {p.codice for p in panel}
    ricevuti = [p.codice for p in risposta.persone]
    if set(ricevuti) != attesi or len(ricevuti) != len(attesi):
        mancanti = sorted(attesi - set(ricevuti))
        extra = sorted(set(ricevuti) - attesi)
        raise ErroreRisposta(
            f"Segmento {risposta.indice}: persone mancanti {mancanti}, inattese {extra}"
        )
    if con_b and any(p.b is None for p in risposta.persone):
        raise ErroreRisposta(f"Segmento {risposta.indice}: manca la valutazione della proposta B")
    return risposta
