import duckdb
import pytest

from app.core import db


@pytest.fixture
def con(tmp_path):
    connessione = db.connetti(tmp_path / "test.duckdb")
    db.crea_schema(connessione)
    yield connessione
    connessione.close()


def test_tutte_le_tabelle_create(con):
    assert set(db.TABELLE) <= db.tabelle_presenti(con)
    assert db.schema_completo(con)


def test_schema_idempotente(con):
    db.crea_schema(con)
    db.crea_schema(con)
    assert db.schema_completo(con)


def test_estensione_spatial_attiva(con):
    con.execute(
        "INSERT INTO area (tipo, codice, nome, geometria) "
        "VALUES ('circoscrizione', '1', 'Prova', ST_Point(7.68, 45.07))"
    )
    x, y = con.execute("SELECT ST_X(geometria), ST_Y(geometria) FROM area").fetchone()
    assert (x, y) == (7.68, 45.07)


def test_codici_sono_stringhe(con):
    tipi = dict(
        con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'sezione_area'"
        ).fetchall()
    )
    assert tipi["sezione"] == "VARCHAR"
    assert tipi["circoscrizione"] == "VARCHAR"


def test_vincoli(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO area (tipo, codice) VALUES ('quartiere', 'x')")
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO contenuto (candidato, formato, testo, stato) "
            "VALUES ('x', 'post', 'y', 'pubblicato')"
        )
    con.execute("INSERT INTO contenuto (candidato, formato, testo) VALUES ('x', 'post', 'y')")
    assert con.execute("SELECT stato FROM contenuto").fetchone()[0] == "bozza"


def test_flag_dati_di_prova(con):
    assert not db.dati_di_prova(con)
    con.execute("INSERT INTO caricamento (fonte, righe, di_prova) VALUES ('fixture', 1, true)")
    assert db.dati_di_prova(con)
