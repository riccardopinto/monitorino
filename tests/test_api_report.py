import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import crea_app
from tests.test_report_dati import popola


@pytest.fixture
def client(tmp_path):
    percorso = tmp_path / "r.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        popola(con)
    with TestClient(crea_app(percorso, cartella_report=tmp_path / "out")) as c:
        yield c


def test_tipi(client):
    r = client.get("/api/report/tipi").json()
    assert set(r["tipi"]) == {"scheda", "confronto", "bollettino", "simulazione", "kit"}
    assert [e["id"] for e in r["elezioni"]] == [1, 2] and r["ultima_settimana"]
    assert any(c["chiave"] == "sindaco" for c in r["candidati"])


def test_anteprima_e_errori(client):
    r = client.post("/api/report/anteprima", json={"tipo": "scheda", "parametri": {"area": "1"},
                                                  "autore": "Staff"})  # fmt: skip
    assert r.status_code == 200 and "Profilo demografico" in r.text
    assert client.post("/api/report/anteprima", json={"tipo": "boh"}).status_code == 422
    r = client.post("/api/report/anteprima", json={"tipo": "scheda", "parametri": {"area": "9"}})
    assert r.status_code == 422 and "non trovata" in r.text
    r = client.post(
        "/api/report/anteprima",
        json={"tipo": "confronto", "parametri": {"modo": "elezioni", "da": 1, "a": 99}},
    )
    assert r.status_code == 422


def test_genera_archivio_download(client):
    r = client.post("/api/report", json={"tipo": "kit", "parametri": {"candidato": "sindaco"},
                                         "titolo": "Kit di prova", "autore": "Staff"})  # fmt: skip
    if r.status_code == 503:
        pytest.skip(r.json()["detail"])
    assert r.status_code == 200, r.text
    esito = r.json()
    assert esito["titolo"] == "Kit di prova" and esito["pagine"] >= 2
    archivio = client.get("/api/report").json()["report"]
    assert archivio[0]["id"] == esito["id"] and archivio[0]["autore"] == "Staff"
    pdf = client.get(esito["url"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert pdf.headers["content-type"] == "application/pdf"
    assert client.get("/api/report/999/pdf").status_code == 404
