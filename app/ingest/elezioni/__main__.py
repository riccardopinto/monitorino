"""Ingest dei risultati elettorali per sezione.

Uso:
    uv run python -m app.ingest.elezioni                 # tutte le consultazioni
    uv run python -m app.ingest.elezioni europee_2024    # solo alcune
"""

from __future__ import annotations

import sys
import time

from app.core import db
from app.core.config import impostazioni
from app.ingest.elezioni.carica import carica
from app.ingest.elezioni.consultazioni import CONSULTAZIONI, PER_CHIAVE


def main(chiavi: list[str]) -> None:
    sconosciute = [k for k in chiavi if k not in PER_CHIAVE]
    if sconosciute:
        raise SystemExit(f"Consultazioni sconosciute: {sconosciute}. Valide: {list(PER_CHIAVE)}")
    scelte = [PER_CHIAVE[k] for k in chiavi] if chiavi else list(CONSULTAZIONI)
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        for c in scelte:
            inizio = time.perf_counter()
            eid = carica(con, c)
            n_sez, n_ris = con.execute(
                "SELECT (SELECT count(*) FROM affluenza WHERE elezione_id = $1), "
                "(SELECT count(*) FROM risultato WHERE elezione_id = $1)",
                [eid],
            ).fetchone()
            print(
                f"{c.nome:32} id={eid:<3} sezioni={n_sez:<4} risultati={n_ris:<8} "
                f"({time.perf_counter() - inizio:.1f}s)"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
