from datetime import date
from pathlib import Path

import pytest

from app.core import db
from app.temi import news

FEED = (Path(__file__).parent / "dati" / "rss" / "feed_prova.xml").read_bytes()


def test_lettura_feed():
    a = news.leggi_feed(FEED, "Prova", "news")
    assert [x.url for x in a] == [
        "https://esempio.test/torino/1",
        "https://esempio.test/torino/2",
        "https://esempio.test/torino/3",
    ]
    assert a[0].titolo == "Nuovo parco in via Esempio a San Paolo"
    assert a[0].sintesi == "Il consiglio della Circoscrizione 3 approva il progetto & i fondi."
    assert a[0].data == date(2026, 11, 16)
    assert a[1].sintesi == ""  # sommario uguale al titolo
    assert len(a[2].sintesi) <= news.SINTESI_MAX and a[2].sintesi.endswith("…")


def test_feed_illeggibile():
    with pytest.raises(ValueError):
        news.leggi_feed(b"<html>non un feed", "Prova", "news")


def test_scrittura_senza_doppioni(tmp_path):
    con = db.connetti(tmp_path / "n.duckdb")
    db.crea_schema(con)
    a = news.leggi_feed(FEED, "Prova", "news")
    assert news.scrivi(con, a) == 3
    assert news.scrivi(con, a) == 0
    righe = con.execute("SELECT tipo_fonte, testo, scadenza FROM documento ORDER BY id").fetchall()
    assert all(r == ("news", None, None) for r in righe)  # niente testo integrale
    con.close()
