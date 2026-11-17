"""Dipendenze condivise dai router."""

from collections.abc import Iterator

import duckdb
from fastapi import Request


def cursore(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    """Un cursore DuckDB per richiesta: la connessione principale non è thread-safe."""
    with request.app.state.db.cursor() as cur:
        yield cur
