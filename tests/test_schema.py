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


VECCHIO_RISULTATO = """
CREATE TABLE risultato (
    elezione_id INTEGER NOT NULL, sezione VARCHAR NOT NULL, tipo_soggetto VARCHAR NOT NULL,
    soggetto VARCHAR NOT NULL, voti INTEGER NOT NULL,
    PRIMARY KEY (elezione_id, sezione, tipo_soggetto, soggetto)
)"""


def test_migrazione_risultato_vuoto(tmp_path):
    c = db.connetti(tmp_path / "m.duckdb")
    c.execute(VECCHIO_RISULTATO)
    db.crea_schema(c)
    assert "gruppo" in db._colonne(c, "risultato")
    c.close()


def test_migrazione_rifiuta_tabella_con_dati(tmp_path):
    c = db.connetti(tmp_path / "m.duckdb")
    c.execute(VECCHIO_RISULTATO)
    c.execute("INSERT INTO risultato VALUES (1, '1', 'lista', 'X', 3)")
    with pytest.raises(RuntimeError):
        db.crea_schema(c)
    c.close()


def test_preferenze_omonime_in_liste_diverse(con):
    con.execute(
        "INSERT INTO risultato (elezione_id, sezione, tipo_soggetto, soggetto, gruppo, voti) "
        "VALUES (1, '1', 'preferenza', 'Mario ROSSI', 'Lista A', 3), "
        "(1, '1', 'preferenza', 'Mario ROSSI', 'Lista B', 5)"
    )
    assert con.execute("SELECT count(*) FROM risultato").fetchone()[0] == 2


def test_flag_dati_di_prova(con):
    assert not db.dati_di_prova(con)
    con.execute("INSERT INTO caricamento (fonte, righe, di_prova) VALUES ('fixture', 1, true)")
    assert db.dati_di_prova(con)
