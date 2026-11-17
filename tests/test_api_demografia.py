from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.analysis import demografia as dm
from app.core import db
from app.main import crea_app
from tests.test_analisi_elezioni import _elezione


@pytest.fixture
def client(tmp_path):
    percorso = tmp_path / "api.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        con.execute(
            "INSERT INTO area (id, tipo, codice) VALUES "
            "(1, 'circoscrizione', '1'), (2, 'circoscrizione', '2'), "
            "(10, 'sezione', '1'), (11, 'sezione', '2'), (12, 'sezione', '3')"
        )
        righe = []
        for area, pop, laureati in ((1, 1000, 300), (2, 1000, 100)):
            righe += [
                (area, 2021, "cens_pop", pop, dm.ISTAT),
                (area, 2021, "cens_pop_9piu", pop, dm.ISTAT),
                (area, 2021, "cens_istr_terziario", laureati, dm.ISTAT),
                (area, 2021, "cens_m_eta_00_04", pop / 2, dm.ISTAT),
                (area, 2021, "cens_f_eta_00_04", pop / 2, dm.ISTAT),
                (area, 2025, "pop_m_eta_000", pop / 2, dm.COMUNE),
                (area, 2025, "pop_f_eta_000", pop / 2, dm.COMUNE),
                (area, 2025, "pop_eta_000", pop, dm.COMUNE),
            ]
        # sezioni: la 3 ha meno di 100 residenti e va nascosta
        for area, pop in ((10, 500), (11, 400), (12, 30)):
            righe += [
                (area, 2021, "cens_pop", pop, dm.ISTAT),
                (area, 2021, "cens_pop_9piu", pop, dm.ISTAT),
                (area, 2021, "cens_istr_terziario", pop / 5, dm.ISTAT),
            ]
        con.executemany("INSERT INTO demografia VALUES (?, ?, ?, ?, ?)", righe)
        sezioni = {str(i): (100, {"A": 30 + i, "B": 20}) for i in (1, 2, 3)}
        _elezione(con, 1, date(2021, 1, 1), {"A": "centrosinistra", "B": "centrodestra"}, sezioni)
    with TestClient(crea_app(percorso)) as c:
        yield c


def test_elenco_indicatori(client):
    el = client.get("/api/demografia/indicatori").json()
    chiavi = {i["chiave"] for i in el}
    assert {"indice_vecchiaia", "quota_stranieri", "reddito_medio"} <= chiavi
    laureati = next(i for i in el if i["chiave"] == "quota_laureati")
    assert laureati["livelli"]["sezione"]["fonte"] == dm.ISTAT


def test_mappa_e_soglia(client):
    m = client.get(
        "/api/demografia/mappa",
        params={"indicatore": "quota_laureati", "livello": "circoscrizione"},
    ).json()
    assert {v["codice"]: v["valore"] for v in m["valori"]} == {"1": 30.0, "2": 10.0}
    assert m["citta"] == 20.0
    s = client.get(
        "/api/demografia/mappa", params={"indicatore": "quota_laureati", "livello": "sezione"}
    ).json()
    valori = {v["codice"]: v["valore"] for v in s["valori"]}
    assert valori["1"] == 20.0 and valori["3"] is None
    assert "100 residenti" in s["nota"]


def test_scheda_area(client):
    s = client.get("/api/demografia/area", params={"livello": "circoscrizione", "codice": "1"})
    s = s.json()
    laureati = next(r for r in s["indicatori"] if r["chiave"] == "quota_laureati")
    assert laureati["valore"] == 30.0 and laureati["citta"] == 20.0
    assert s["piramide"]["maschi"][0] == 50.0
    assert (
        client.get(
            "/api/demografia/area", params={"livello": "sezione", "codice": "99"}
        ).status_code
        == 404
    )


def test_dispersione(client):
    d = client.get(
        "/api/demografia/dispersione",
        params={
            "indicatore": "quota_laureati",
            "elezione": 1,
            "soggetto": "centrosinistra",
            "livello": "sezione",
        },
    ).json()
    assert d["n"] == 2  # la sezione 3 è sotto soglia
    assert "non dice come hanno votato" in d["nota"]


def test_indicatore_sconosciuto(client):
    r = client.get("/api/demografia/mappa", params={"indicatore": "xyz"})
    assert r.status_code == 404
