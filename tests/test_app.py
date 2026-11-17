from fastapi.testclient import TestClient

from app.core import db
from app.main import crea_app


def test_pagina_e_stato(tmp_path):
    percorso = tmp_path / "app.duckdb"
    with TestClient(crea_app(percorso)) as client:
        pagina = client.get("/")
        assert pagina.status_code == 200
        assert "Monitorino" in pagina.text

        assert client.get("/static/vendor/alpine.min.js").status_code == 200

        stato = client.get("/api/stato").json()
        assert stato["schema_completo"] is True
        assert stato["dati_di_prova"] is False


def test_stato_segnala_dati_di_prova(tmp_path):
    percorso = tmp_path / "app.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        con.execute("INSERT INTO caricamento (fonte, righe, di_prova) VALUES ('fixture', 1, true)")
    with TestClient(crea_app(percorso)) as client:
        assert client.get("/api/stato").json()["dati_di_prova"] is True
