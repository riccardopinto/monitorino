import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, shape

from app.core import db
from app.main import crea_app


@pytest.fixture
def client(tmp_path):
    percorso = tmp_path / "app.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        con.execute(
            "INSERT INTO area (id, tipo, codice, nome, geometria) VALUES "
            "(1, 'circoscrizione', '3', 'San Paolo', ST_GeomFromWKB(?))",
            [box(7.60, 45.00, 7.62, 45.02).wkb],
        )
        con.execute(
            "INSERT INTO area (id, tipo, codice, nome, geometria, id_padre, approssimata) VALUES "
            "(2, 'sezione', '10', 'Sezione 10', ST_GeomFromWKB(?), 1, true), "
            "(3, 'sezione', '11', 'Sezione 11', NULL, 1, true)",
            [box(7.60, 45.00, 7.61, 45.01).wkb],
        )
    with TestClient(crea_app(percorso)) as c:
        yield c


def test_circoscrizioni_geojson(client):
    r = client.get("/api/aree", params={"tipo": "circoscrizione"})
    assert r.status_code == 200
    dati = r.json()
    assert dati["type"] == "FeatureCollection"
    (f,) = dati["features"]
    assert f["properties"] == {
        "id": 1,
        "tipo": "circoscrizione",
        "codice": "3",
        "nome": "San Paolo",
        "circoscrizione": "3",
        "approssimata": False,
    }
    assert shape(f["geometry"]).equals(box(7.60, 45.00, 7.62, 45.02))


def test_sezioni_con_circoscrizione_e_senza_geometrie_nulle(client):
    dati = client.get("/api/aree", params={"tipo": "sezione"}).json()
    (f,) = dati["features"]  # la sezione 11 senza geometria non compare
    assert f["properties"]["circoscrizione"] == "3"
    assert f["properties"]["approssimata"] is True


def test_tipo_non_valido(client):
    assert client.get("/api/aree", params={"tipo": "quartiere"}).status_code == 422


def test_stato_riporta_sfondo(client):
    assert client.get("/api/stato").json()["mappa_sfondo"] == "nessuna"
