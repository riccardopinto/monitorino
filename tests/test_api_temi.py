import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import crea_app

TEMA = "verde pubblico e parchi"


@pytest.fixture
def client(tmp_path):
    percorso = tmp_path / "t.duckdb"
    oggi = date.today()
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        con.execute("INSERT INTO area (id, tipo, codice) VALUES (13, 'circoscrizione', '3')")
        con.executemany(
            "INSERT INTO documento (id, fonte, tipo_fonte, titolo, url, data, testo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "Testata", "news", "Parco a San Paolo", "https://x.test/1", oggi, None),
                (2, "Testata", "news", "Altro parco", "https://x.test/2", oggi, None),
                (3, "Bluesky", "social", None, None, oggi, "Testo social da non mostrare"),
            ],
        )
    with TestClient(crea_app(percorso)) as c:
        yield c


def _classificazioni():
    voci = [
        {"id": i, "pertinente": True, "tema": TEMA, "sentiment": s, "circoscrizione": circ,
         "sintesi": "Sintesi."}
        for i, s, circ in ((1, 1, "3"), (2, -1, None), (3, 0, "3"))
    ]  # fmt: skip
    return json.dumps({"classificazioni": voci})


def test_flusso_chat_e_matrice(client):
    st = client.get("/api/temi/stato").json()
    assert st["documenti"] == 3 and st["da_classificare"] == 3

    p = client.get("/api/temi/prompt")
    assert p.status_code == 200 and "attachment" in p.headers["content-disposition"]
    assert "[id 3] Bluesky (social)" in p.text

    r = client.post(
        "/api/temi/classificazioni",
        content=_classificazioni(),
        headers={"Content-Type": "text/plain"},
    ).json()
    assert r["applicati"] == 3 and r["righe_aggregate"] == 2

    m = client.get("/api/temi/matrice").json()
    assert m["temi"] == [TEMA]
    assert m["citta"][TEMA]["volume"] == 3
    assert m["celle"] == [{"tema": TEMA, "area": "3", "volume": 2, "sentiment": 0.5}]

    a = client.get("/api/temi/andamento", params={"area": "3", "settimane": 4}).json()
    assert a["serie"][0]["tema"] == TEMA and a["serie"][0]["volumi"][-1] == 2


def test_articoli_solo_news(client):
    client.post(
        "/api/temi/classificazioni",
        content=_classificazioni(),
        headers={"Content-Type": "text/plain"},
    )
    art = client.get("/api/temi/articoli", params={"tema": TEMA}).json()
    assert {a["testata"] for a in art} == {"Testata"}
    assert all("social" not in json.dumps(a) for a in art)
    soc = client.get("/api/temi/social").json()
    assert soc == {"conteggi": [{"tema": TEMA, "area": "3", "n": 1}]}  # solo numeri


def test_errori(client):
    r = client.post(
        "/api/temi/classificazioni", content="non è json", headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 422
    assert client.get("/api/temi/andamento", params={"area": "9"}).status_code == 404


def test_date_settimana():
    from app.api.temi import _dal

    d = _dal(1)
    assert d.weekday() == 0 and d <= date.today() < d + timedelta(weeks=1)


def test_esclusione_e_riepilogo_aree(client):
    client.post(
        "/api/temi/classificazioni",
        content=_classificazioni(),
        headers={"Content-Type": "text/plain"},
    )
    r = client.get("/api/temi/aree").json()
    # documenti di oggi, nessuno nelle settimane precedenti: il tema è nuovo
    assert r["aree"]["3"] == {"temi": 1, "nuovi": [TEMA]}

    assert client.put(f"/api/temi/esclusi/{TEMA}").json() == {"esclusi": [TEMA]}
    m = client.get("/api/temi/matrice").json()
    assert m["temi"] == [] and m["celle"] == [] and m["esclusi"] == [TEMA]
    assert client.get("/api/temi/aree").json()["aree"] == {}
    assert client.get("/api/temi/andamento").json()["serie"] == []

    assert client.delete(f"/api/temi/esclusi/{TEMA}").json() == {"esclusi": []}
    assert client.get("/api/temi/matrice").json()["temi"] == [TEMA]


def test_tema_vecchio_non_nuovo(client):
    oggi = date.today()
    lunedi = oggi - timedelta(days=oggi.weekday())
    con = client.app.state.db
    con.executemany(
        "INSERT INTO tema_aggregato VALUES (?, 13, ?, 2, 0, 1)",
        [("traffico", lunedi), ("traffico", lunedi - timedelta(weeks=2))],
    )
    assert client.get("/api/temi/aree").json()["aree"]["3"] == {"temi": 1, "nuovi": []}
