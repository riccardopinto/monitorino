from datetime import date
from pathlib import Path

import pytest

from app.core import db
from app.ingest.elezioni.carica import ErroreIngest, carica, leggi_consultazione, tabelle
from app.ingest.elezioni.consultazioni import CONSULTAZIONI, Consultazione, File

DATI = Path(__file__).parent / "dati" / "elezioni"


def _locale(url: str, fonte: str) -> Path:
    return DATI / url.rsplit("/", 1)[-1]


# La chiave comunali_2021 fa usare la classificazione reale di config/aree_politiche.yaml.
PROVA = Consultazione(
    "comunali_2021",
    "comunali",
    date(2021, 10, 3),
    1,
    "Prova 2021",
    "prova",
    (
        File("/x/sindaco_2021.csv", "candidato_sindaco", affluenza=True),
        File("/x/preferenze_2021.csv", "preferenza"),
    ),
)


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    yield c
    c.close()


def test_carica_e_idempotente(con):
    eid = carica(con, PROVA, scaricatore=_locale, totali_ufficiali=False)
    assert carica(con, PROVA, scaricatore=_locale, totali_ufficiali=False) == eid
    assert con.execute("SELECT count(*) FROM elezione").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM affluenza").fetchone()[0] == 3
    sindaco = con.execute(
        "SELECT sum(voti) FROM risultato WHERE tipo_soggetto = 'candidato_sindaco' "
        "AND sezione = '1'"
    ).fetchone()[0]
    validi = con.execute("SELECT voti_validi FROM affluenza WHERE sezione = '1'").fetchone()[0]
    assert sindaco == validi
    # preferenze: gruppo = lista, niente righe a zero
    gruppi, zeri = con.execute(
        "SELECT list(DISTINCT gruppo), count(*) FILTER (voti = 0) FROM risultato "
        "WHERE tipo_soggetto = 'preferenza'"
    ).fetchone()
    # nelle 3 sezioni del file di prova la lista può non avere preferenze (lista vuota = NULL)
    assert gruppi in (None, ["PARTITO COMUNISTA DEI LAVORATORI"])
    assert zeri == 0
    assert con.execute("SELECT DISTINCT anno FROM sezione_area").fetchall() == [(2021,)]


def test_conflitto_di_circoscrizione(con):
    carica(con, PROVA, scaricatore=_locale, totali_ufficiali=False)
    con.execute("UPDATE sezione_area SET circoscrizione = '5' WHERE sezione = '1'")
    altra = Consultazione(
        "comunali_2021", "europee", date(2021, 5, 1), 1, "Bis", "prova", PROVA.file
    )
    with pytest.raises(ErroreIngest):
        carica(con, altra, scaricatore=_locale, totali_ufficiali=False)


def test_affluenza_obbligatoria():
    senza = Consultazione(
        "x",
        "comunali",
        date(2021, 1, 1),
        1,
        "x",
        "x",
        (File("/x/preferenze_2021.csv", "preferenza"),),
    )
    with pytest.raises(ErroreIngest):
        tabelle(leggi_consultazione(senza, scaricatore=_locale))


def test_definizioni_coerenti():
    chiavi = [c.chiave for c in CONSULTAZIONI]
    assert len(chiavi) == len(set(chiavi))
    naturali = [(c.tipo, c.data, c.turno) for c in CONSULTAZIONI]
    assert len(naturali) == len(set(naturali))
    for c in CONSULTAZIONI:
        assert any(f.affluenza for f in c.file), c.chiave
