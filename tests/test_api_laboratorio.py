import pytest
from fastapi.testclient import TestClient

from app.api import laboratorio
from app.core import db
from app.llm import simulazione as sim
from app.llm.client import ClientLLM
from app.main import crea_app
from tests.test_simulazione import PREZZI, SEGMENTI, SDKFinto, _imp, _risposta_blocco, popola

DICITURA = "Simulazione IA, non è un sondaggio"


@pytest.fixture
def app_db(tmp_path):
    percorso = tmp_path / "t.duckdb"
    with db.connetti(percorso) as con:
        db.crea_schema(con)
        popola(con)
    app = crea_app(percorso)
    with TestClient(app) as c:
        yield app, c


@pytest.fixture
def client(app_db):
    return app_db[1]


def _corpo(**kw):
    return {"proposta": "Un nuovo parco", "candidato": "sindaco", "aree": ["3", "4"],
            "segmenti": SEGMENTI, "persone": 3, "seed": 7, **kw}  # fmt: skip


def test_opzioni(client):
    r = client.get("/api/laboratorio/opzioni").json()
    assert r["dicitura"] == DICITURA and len(r["limiti"]) >= 5
    sindaco = next(c for c in r["candidati"] if c["chiave"] == "sindaco")
    assert all(s["area_di_voto"] != "M5S" for s in sindaco["segmenti_elettorato"])
    assert "favorevoli_pct" in r["metriche_calibrazione"]


def test_flusso_chat_via_api(client, app_db):
    r = client.post("/api/laboratorio/simulazioni", json=_corpo())
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["dicitura"] == DICITURA and v["stato"] == "in_attesa" and len(v["blocchi"]) == 2
    assert "panel" not in v and v["aggregati"] is None
    sid = v["id"]
    p = client.get(f"/api/laboratorio/simulazioni/{sid}/prompt/1")
    assert p.status_code == 200 and DICITURA in p.text
    assert "attachment" in p.headers["content-disposition"]
    run = sim.carica(app_db[0].state.db.cursor(), sid)
    for n in (1, 2):
        r = client.post(
            f"/api/laboratorio/simulazioni/{sid}/risposte/{n}",
            content=_risposta_blocco(run, n),
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code == 200, r.text
    v = r.json()["simulazione"]
    assert v["stato"] == "completata" and v["aggregati"]["a"]["totale"]["n"] == 12
    assert v["dicitura"] == DICITURA
    s = client.get(f"/api/laboratorio/simulazioni/{sid}/prompt-sintesi")
    assert s.status_code == 200 and "Riepilogo numerico" in s.text
    v = client.post(
        f"/api/laboratorio/simulazioni/{sid}/sintesi",
        content="Sintesi",
        headers={"Content-Type": "text/plain"},
    ).json()
    assert v["sintesi"] == "Sintesi"
    archivio = client.get("/api/laboratorio/simulazioni").json()
    assert archivio["dicitura"] == DICITURA
    assert archivio["simulazioni"][0]["totale"]["n"] == 12

    c = client.post("/api/laboratorio/calibrazioni", json={
        "simulazione_id": sid, "fonte_sondaggio": "Istituto X", "metrica": "favorevoli_pct",
        "valore_reale": 30, "data_sondaggio": "2026-11-01"})  # fmt: skip
    assert c.status_code == 200, c.text
    assert c.json()["affidabilita"]["n"] == 1
    a = client.get("/api/laboratorio/affidabilita").json()
    assert a["dicitura"] == DICITURA and a["n"] == 1


def test_errori(client):
    assert client.get("/api/laboratorio/simulazioni/99").status_code == 404
    r = client.post("/api/laboratorio/simulazioni", json=_corpo(aree=["9"]))
    assert r.status_code == 422 and "sconosciute" in r.text
    r = client.post("/api/laboratorio/simulazioni", json=_corpo(candidato="nessuno"))
    assert r.status_code == 422
    sid = client.post("/api/laboratorio/simulazioni", json=_corpo()).json()["id"]
    r = client.post(
        f"/api/laboratorio/simulazioni/{sid}/risposte/1",
        content="{}",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422
    assert client.get(f"/api/laboratorio/simulazioni/{sid}/prompt-sintesi").status_code == 409


def test_api_senza_chiave(client, monkeypatch):
    monkeypatch.setattr(laboratorio, "api_disponibile", lambda: False)
    r = client.post("/api/laboratorio/simulazioni", json=_corpo(origine="api"))
    assert r.status_code == 409 and "flusso chat" in r.text


def test_flusso_api_con_conferma(app_db, monkeypatch):
    app, client = app_db
    monkeypatch.setattr(laboratorio, "api_disponibile", lambda: True)
    monkeypatch.setattr(laboratorio.sim, "impostazioni", lambda: _imp(soglia=0.0001))
    monkeypatch.setattr(laboratorio.sim, "prezzi_llm", lambda: PREZZI)
    sdk = SDKFinto(gradimento=5)
    app.dependency_overrides[laboratorio.client_llm] = lambda: ClientLLM(
        app.state.db.cursor(), imp=_imp(), prezzi=PREZZI, sdk=sdk
    )
    v = client.post("/api/laboratorio/simulazioni", json=_corpo(origine="api")).json()
    assert v["stima"]["chiamate"] == 4 and v["modello"] == "modello-prova"
    r = client.post(f"/api/laboratorio/simulazioni/{v['id']}/avvia")
    assert r.status_code == 409 and r.json()["detail"]["conferma_richiesta"] is True
    assert sdk.chiamate == []
    r = client.post(f"/api/laboratorio/simulazioni/{v['id']}/avvia?conferma=true")
    assert r.status_code == 200, r.text
    v = r.json()["simulazione"]
    assert v["stato"] == "completata" and v["costo_eur"] > 0 and len(sdk.chiamate) == 4
    assert v["dicitura"] == DICITURA
