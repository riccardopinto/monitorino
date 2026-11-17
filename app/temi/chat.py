"""Classificazione senza chiave API: prompt da incollare in una chat e importazione del JSON.

1. ``uv run python -m app.temi esporta`` scrive in data/processed/ uno o più file
   temi_prompt_<data>_<n>.md, ciascuno con istruzioni e fino a 150 documenti;
2. si incolla un file in una nuova chat e si salva la risposta (solo JSON) in un file;
3. ``uv run python -m app.temi importa risposta.json`` valida e salva le classificazioni.

Le istruzioni sono le stesse della classificazione via API (app/llm/prompt_temi.py).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from app.ingest._comune import DIR_PROCESSED
from app.llm import prompt_temi as pt

PER_FILE = 150


def prompt(documenti: list[dict]) -> str:
    esempio = {
        "classificazioni": [
            {
                "id": documenti[0]["id"] if documenti else 1,
                "pertinente": True,
                "tema": pt.tassonomia()[0],
                "sentiment": 0,
                "circoscrizione": None,
                "sintesi": "Frase neutra di massimo 25 parole.",
            }
        ]
    }
    return f"""# Classificazione dei temi (Monitorino)

{pt.istruzioni()}

## Formato della risposta

Rispondi con un unico blocco JSON valido, senza testo prima o dopo, con questa struttura
(un elemento per ciascuno dei {len(documenti)} documenti):

```json
{json.dumps(esempio, ensure_ascii=False, indent=2)}
```

Schema completo:

```json
{json.dumps(pt.schema_risposta(), ensure_ascii=False)}
```

## Documenti ({len(documenti)})

{pt.formatta_documenti(documenti)}
"""


def esporta(
    con: duckdb.DuckDBPyConnection, cartella: Path = DIR_PROCESSED, per_file: int = PER_FILE
) -> list[Path]:
    documenti = pt.documenti_da_classificare(con)
    cartella.mkdir(parents=True, exist_ok=True)
    file = []
    for n, inizio in enumerate(range(0, len(documenti), per_file), start=1):
        blocco = documenti[inizio : inizio + per_file]
        p = cartella / f"temi_prompt_{date.today():%Y%m%d}_{n}.md"
        p.write_text(prompt(blocco), encoding="utf-8")
        file.append(p)
    return file


def importa(con: duckdb.DuckDBPyConnection, testo: str) -> dict[str, list]:
    voci = pt.estrai_json(testo)
    con.execute("BEGIN")
    try:
        esito = pt.applica(con, voci, origine="chat")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return esito
