"""Comandi del modulo temi.

    uv run python -m app.temi news          raccolta news (feed RSS) e geolocalizzazione
    uv run python -m app.temi social        raccolta dai social attivi in config/fonti.yaml
    uv run python -m app.temi luoghi        ricostruisce il dizionario dei luoghi
    uv run python -m app.temi esporta       prompt per classificare in una chat (senza API)
    uv run python -m app.temi importa FILE  importa il JSON della risposta della chat
    uv run python -m app.temi classifica    classificazione con la Batches API (serve la chiave)
    uv run python -m app.temi aggrega       aggregazione settimanale in tema_aggregato
    uv run python -m app.temi pulisci       cancella i testi scaduti (30 giorni)
    uv run python -m app.temi tutto         news + social + aggrega + pulisci

L'app deve essere spenta: DuckDB ammette un solo processo in scrittura. Con l'app accesa e
RACCOLTA_AUTOMATICA=true lo stesso lavoro lo fa il pianificatore interno.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from app.core import db
from app.core.config import impostazioni
from app.temi import aggrega, chat, luoghi, news, social


def esegui_raccolta(con: duckdb.DuckDBPyConnection) -> dict:
    """Raccolta giornaliera completa (usata anche dal pianificatore)."""
    esito = {"news": news.raccogli(con), "social": social.raccogli(con)}
    if con.execute("SELECT count(*) FROM luogo").fetchone()[0]:
        esito["geolocalizzazione"] = luoghi.geolocalizza(con)
    esito["aggregati"] = aggrega.aggrega(con)
    esito["testi_cancellati"] = aggrega.pulisci(con)
    return esito


def _stampa(esito, rientro: str = "") -> None:
    if isinstance(esito, dict):
        for k, v in esito.items():
            if isinstance(v, dict | list) and v:
                print(f"{rientro}{k}:")
                _stampa(v, rientro + "  ")
            else:
                print(f"{rientro}{k}: {v}")
    elif isinstance(esito, list):
        for v in esito:
            print(f"{rientro}- {v}")
    else:
        print(f"{rientro}{esito}")


def main(argomenti: list[str]) -> None:
    if not argomenti:
        raise SystemExit(__doc__)
    comando = argomenti[0]
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        if comando == "news":
            esito = news.raccogli(con)
            if con.execute("SELECT count(*) FROM luogo").fetchone()[0]:
                esito["geolocalizzazione"] = luoghi.geolocalizza(con)
        elif comando == "social":
            esito = social.raccogli(con)
        elif comando == "luoghi":
            nomi = dict(
                con.execute(
                    "SELECT codice, nome FROM area WHERE tipo = 'circoscrizione'"
                ).fetchall()
            )
            n = luoghi.salva(con, luoghi.costruisci(luoghi.leggi_civici(), nomi))
            esito = {"luoghi": n, "geolocalizzazione": luoghi.geolocalizza(con, solo_nuovi=False)}
        elif comando == "esporta":
            file = chat.esporta(con)
            esito = {"file": [str(p) for p in file]} if file else "nessun documento da classificare"
        elif comando == "importa":
            if len(argomenti) < 2:
                raise SystemExit("Uso: python -m app.temi importa risposta.json")
            risultato = chat.importa(con, Path(argomenti[1]).read_text(encoding="utf-8"))
            esito = {k: len(v) if k == "applicati" else v for k, v in risultato.items()}
        elif comando == "classifica":
            from app.llm.classificazione import classifica

            esito = classifica(con)
        elif comando == "aggrega":
            esito = {"righe": aggrega.aggrega(con)}
        elif comando == "pulisci":
            esito = {"testi_cancellati": aggrega.pulisci(con)}
        elif comando == "tutto":
            esito = esegui_raccolta(con)
        else:
            raise SystemExit(f"Comando sconosciuto: {comando}\n{__doc__}")
    _stampa(esito)


if __name__ == "__main__":
    main(sys.argv[1:])
