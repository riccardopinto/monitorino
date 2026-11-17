"""Aggregazione settimanale dei temi e pulizia dei testi scaduti."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

SETTIMANE = 12


def aggrega(con: duckdb.DuckDBPyConnection, settimane: int = SETTIMANE) -> int:
    """Ricalcola tema_aggregato per le ultime ``settimane``.

    Una riga per tema, settimana (lunedì) e circoscrizione, più una riga cittadina (area NULL)
    che conta tutti i documenti, anche quelli senza circoscrizione. Si usano solo i documenti
    classificati e pertinenti per la città.
    """
    oggi = date.today()
    dal = oggi - timedelta(days=oggi.weekday()) - timedelta(weeks=max(1, settimane))
    base = (
        "FROM documento WHERE tema IS NOT NULL AND coalesce(pertinente, true) "
        "AND data >= ? AND data <= ?"
    )
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM tema_aggregato WHERE settimana >= ?", [dal])
        con.execute(
            f"""
            INSERT INTO tema_aggregato (tema, area_id, settimana, volume, sentiment_medio, n_fonti)
            SELECT tema, area_id, date_trunc('week', data)::DATE, count(*), avg(sentiment),
                   count(DISTINCT fonte)
            {base} AND area_id IS NOT NULL GROUP BY ALL
            UNION ALL
            SELECT tema, NULL, date_trunc('week', data)::DATE, count(*), avg(sentiment),
                   count(DISTINCT fonte)
            {base} GROUP BY ALL
            """,
            [dal, oggi, dal, oggi],
        )
        (n,) = con.execute(
            "SELECT count(*) FROM tema_aggregato WHERE settimana >= ?", [dal]
        ).fetchone()
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def pulisci(con: duckdb.DuckDBPyConnection) -> int:
    """Cancella il testo originale dei documenti scaduti (contenuti social dopo 30 giorni)."""
    righe = con.execute(
        "UPDATE documento SET testo = NULL "
        "WHERE testo IS NOT NULL AND scadenza IS NOT NULL AND scadenza <= current_date "
        "RETURNING id"
    ).fetchall()
    return len(righe)
