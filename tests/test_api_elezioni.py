from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import crea_app
from tests.test_analisi_elezioni import _elezione


@pytest.fixture
def client(tmp_path):
    percorso = tmp_path / "api.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        sezioni = {str(i): (100, {"A": 30 + i % 7, "B": 20 + i % 5}) for i in range(1, 41)}
        _elezione(con, 1, date(2021, 1, 1), {"A": "centrosinistra", "B": "centrodestra"}, sezioni)
        sezioni2 = {str(i): (100, {"A": 25 + i % 3, "B": 28 + i % 4}) for i in range(1, 41)}
        _elezione(con, 2, date(2024, 1, 1), {"A": "centrosinistra", "B": "centrodestra"}, sezioni2)
    with TestClient(crea_app(percorso)) as c:
        yield c


def test_elenco(client):
    el = client.get("/api/elezioni").json()
    assert [e["id"] for e in el] == [1, 2]
    assert set(el[0]["soggetti"]) == {"lista", "forza", "area"}
    assert el[0]["soggetti"]["area"][0] in ("centrosinistra", "centrodestra")


def test_mappa_quota_e_affluenza(client):
    r = client.get(
        "/api/elezioni/1/mappa",
        params={"livello": "circoscrizione", "tipo": "area", "soggetto": "centrosinistra"},
    ).json()
    assert r["unita"] == "%"
    assert {v["codice"] for v in r["valori"]} == {"1", "2"}
    assert 0 < r["citta"] < 100
    aff = client.get("/api/elezioni/1/mappa", params={"metrica": "affluenza"}).json()
    assert aff["unita"] == "%" and len(aff["valori"]) == 2


def test_mappa_variazione(client):
    r = client.get(
        "/api/elezioni/2/mappa",
        params={"metrica": "variazione", "confronto": 1, "soggetto": "centrodestra"},
    ).json()
    assert r["unita"] == "punti"
    assert r["citta"] > 0  # B cresce in tutte le sezioni


def test_errori(client):
    assert client.get("/api/elezioni/99/mappa", params={"soggetto": "x"}).status_code == 404
    assert client.get("/api/elezioni/1/mappa").status_code == 422
    assert (
        client.get(
            "/api/elezioni/1/mappa", params={"metrica": "variazione", "soggetto": "A"}
        ).status_code
        == 422
    )


def test_dettaglio_area(client):
    r = client.get(
        "/api/elezioni/1/area", params={"livello": "circoscrizione", "codice": "1"}
    ).json()
    assert {x["soggetto"] for x in r["righe"]} == {"centrosinistra", "centrodestra"}
    assert all(x["quota_citta"] is not None for x in r["righe"])


def test_flussi(client):
    r = client.get("/api/flussi", params={"da": 1, "a": 2}).json()
    assert r["n_sezioni"] == 40
    assert "Stima" in r["etichetta"]
    for riga in r["quote"]:
        assert sum(riga) == pytest.approx(100, abs=0.5)
