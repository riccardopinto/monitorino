from datetime import date, timedelta

import pytest

from app.core import db
from app.temi import aggrega


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "a.duckdb")
    db.crea_schema(c)
    oggi = date.today()
    lunedi = oggi - timedelta(days=oggi.weekday())
    righe = [
        # fonte, data, tema, sentiment, area, pertinente
        ("A", lunedi, "verde pubblico e parchi", 2, 13, True),
        ("B", lunedi, "verde pubblico e parchi", -2, 13, True),
        ("A", lunedi, "verde pubblico e parchi", 1, None, True),  # solo nel totale città
        ("A", lunedi, "verde pubblico e parchi", 1, 13, False),  # non pertinente: esclusa
        ("A", lunedi, None, None, 13, None),  # non classificata: esclusa
        ("A", lunedi - timedelta(weeks=30), "sport e impianti", 0, 13, True),  # troppo vecchia
    ]
    c.executemany(
        "INSERT INTO documento (fonte, data, tema, sentiment, area_id, pertinente) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        righe,
    )
    yield c, lunedi
    c.close()


def test_aggregazione(con):
    c, lunedi = con
    assert aggrega.aggrega(c) == 2
    righe = c.execute(
        "SELECT tema, area_id, settimana, volume, sentiment_medio, n_fonti FROM tema_aggregato "
        "ORDER BY area_id NULLS FIRST"
    ).fetchall()
    assert righe[0] == ("verde pubblico e parchi", None, lunedi, 3, pytest.approx(1 / 3), 2)
    assert righe[1] == ("verde pubblico e parchi", 13, lunedi, 2, 0.0, 2)
    assert aggrega.aggrega(c) == 2  # idempotente


def test_pulizia_testi_scaduti(tmp_path):
    c = db.connetti(tmp_path / "p.duckdb")
    db.crea_schema(c)
    c.execute(
        "INSERT INTO documento (fonte, testo, scadenza) VALUES "
        "('s', 'scaduto', current_date - 1), ('s', 'oggi', current_date), "
        "('s', 'futuro', current_date + 5), ('n', 'news senza scadenza', NULL)"
    )
    assert aggrega.pulisci(c) == 2
    testi = [r[0] for r in c.execute("SELECT testo FROM documento ORDER BY id").fetchall()]
    assert testi == [None, None, "futuro", "news senza scadenza"]
    c.close()


def test_pianificatore_si_avvia_e_si_ferma(tmp_path):
    from app.temi import pianificatore

    c = db.connetti(tmp_path / "s.duckdb")
    p = pianificatore.avvia(c)
    assert p.get_job("raccolta_temi").next_run_time.hour == pianificatore.ORA_RACCOLTA
    p.shutdown(wait=False)
    c.close()
