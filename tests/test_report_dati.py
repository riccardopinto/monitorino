"""Dati dei report su un database di prova con due circoscrizioni."""

import json
from datetime import date, timedelta

import pytest
from shapely.geometry import box

from app.analysis import demografia as dm
from app.core import db
from app.llm import simulazione as sim
from app.reports import dati
from tests.test_analisi_elezioni import _elezione
from tests.test_simulazione import SEGMENTI, _risposta_blocco

LUNEDI = date.today() - timedelta(days=date.today().weekday())


def popola(con):
    for aid, codice in ((1, "1"), (2, "2")):
        con.execute(
            "INSERT INTO area (id, tipo, codice, nome, geometria) "
            "VALUES (?, 'circoscrizione', ?, ?, ST_GeomFromText(?))",
            [aid, codice, f"Zona {codice} - Borgo", box(7.6 + aid * 0.02, 45.0,
                                                         7.62 + aid * 0.02, 45.02).wkt],
        )  # fmt: skip
        pop = 1000 * aid
        con.executemany(
            "INSERT INTO demografia VALUES (?, ?, ?, ?, ?)",
            [(aid, 2021, "cens_pop", pop, dm.ISTAT), (aid, 2021, "cens_pop_9piu", pop, dm.ISTAT),
             (aid, 2021, "cens_istr_terziario", pop / (3 * aid), dm.ISTAT),
             (aid, 2025, "pop_m_eta_040", pop / 2, dm.COMUNE),
             (aid, 2025, "pop_f_eta_040", pop / 2, dm.COMUNE),
             (aid, 2025, "pop_eta_040", pop, dm.COMUNE)],
        )  # fmt: skip
        for i, s in enumerate(SEGMENTI):
            (sid,) = con.execute(
                "INSERT INTO segmento (definizione) VALUES (?) RETURNING id", [json.dumps(s)]
            ).fetchone()
            con.execute(
                "INSERT INTO segmento_peso VALUES (?, ?, 2025, 'comunali', ?)",
                [sid, aid, 0.2 if i == 0 else 0.4],
            )
    liste = {"A": "centrosinistra", "B": "centrodestra"}
    _elezione(
        con,
        1,
        date(2021, 1, 1),
        liste,
        {str(i): (100, {"A": 30 + i % 7, "B": 20 + i % 5}) for i in range(1, 41)},
    )
    _elezione(
        con,
        2,
        date(2024, 1, 1),
        liste,
        {str(i): (100, {"A": 25 + i % 3, "B": 28 + i % 4}) for i in range(1, 41)},
    )
    con.executemany(
        "INSERT INTO caricamento (fonte, righe, di_prova) VALUES (?, 1, false)",
        [("elezioni:europee_2024",), ("comune_demografia",), ("news",)],
    )
    con.executemany(
        "INSERT INTO tema_aggregato VALUES (?, ?, ?, ?, ?, 1)",
        [("traffico", None, LUNEDI, 5, -0.5), ("traffico", 1, LUNEDI, 3, -1.0),
         ("verde pubblico", None, LUNEDI, 2, 1.0), ("verde pubblico", 2, LUNEDI, 2, 1.0),
         ("traffico", None, LUNEDI - timedelta(weeks=1), 1, 0.0)],
    )  # fmt: skip
    con.execute(
        "INSERT INTO documento (id, fonte, tipo_fonte, titolo, url, data, tema, area_id) "
        "VALUES (1, 'Testata', 'news', 'Code in corso', 'https://x.test/1', ?, 'traffico', 1)",
        [LUNEDI],
    )


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "r.duckdb")
    db.crea_schema(c)
    popola(c)
    yield c
    c.close()


def _ctx(con, tipo, **p):
    return dati.contesto(con, tipo, p, autore="Staff", versione="0.1.0")


def test_scheda(con):
    c = _ctx(con, "scheda", area="1")
    assert c["titolo"] == "Circoscrizione 1" and c["sottotitolo"] == "Zona 1 - Borgo"
    assert c["mappa"].startswith("data:image/png")
    assert [e["id"] for e in c["storico"]] == [1, 2]
    assert 0 < c["storico"][0]["quote"]["centrosinistra"] < 100
    assert c["demografia"] and c["temi"]["celle"][0]["tema"] == "traffico"
    assert {g["id"] for g in c["grafici"]} >= {"g-affluenza", "g-ultima", "g-piramide"}
    assert [f["dato"] for f in c["fonti"]][0] == "Risultati elettorali per sezione"
    with pytest.raises(dati.ErroreDati):
        _ctx(con, "scheda", area="9")


def test_confronto_elezioni_e_aree(con):
    c = _ctx(con, "confronto", modo="elezioni", da=1, a=2)
    assert c["nome_area"] == "Torino" and len(c["righe"]) == 2
    r = {x["soggetto"]: x for x in c["righe"]}
    assert r["centrodestra"]["variazione"] > 0
    assert c["flussi"]["n_sezioni"] == 40 and c["mappa"].startswith("data:image/png")
    c = _ctx(con, "confronto", modo="aree", elezione=1, area1="1", area2="2")
    assert c["affluenza"]["a1"] and c["indicatori"]
    with pytest.raises(dati.ErroreDati, match="diverse"):
        _ctx(con, "confronto", modo="aree", elezione=1, area1="1", area2="1")


def test_bollettino(con):
    c = _ctx(con, "bollettino")
    assert c["settimana"] == LUNEDI
    assert [r["tema"] for r in c["citta"]] == ["traffico", "verde pubblico"]
    assert c["matrice"][0]["celle"] == {"1": 3}
    assert c["nuovi"]["2"]["nuovi"] == ["verde pubblico"]  # traffico c'era già in città, non in 2
    assert c["articoli"][0]["titolo"] == "Code in corso"
    con.execute("INSERT INTO tema_escluso (tema) VALUES ('traffico')")
    assert [r["tema"] for r in _ctx(con, "bollettino")["citta"]] == ["verde pubblico"]


def test_simulazione(con):
    r = sim.Richiesta(
        proposta="Un parco",
        candidato="sindaco",
        aree=["1", "2"],
        segmenti=SEGMENTI,
        persone=3,
        seed=1,
        proposta_b="Un parco grande",
    )
    sid = sim.crea(con, r, "chat")
    with pytest.raises(dati.ErroreDati, match="non è ancora completa"):
        _ctx(con, "simulazione", simulazione=sid)
    run = sim.carica(con, sid)
    for b in run["parametri"]["blocchi"]:
        sim.importa_chat(con, sid, b["n"], _risposta_blocco(run, b["n"], con_b=True))
    c = _ctx(con, "simulazione", simulazione=sid)
    assert c["dicitura"] == "Simulazione IA, non è un sondaggio" and c["limiti"]
    assert c["varianti"] == ["a", "b"] and c["mappa"].startswith("data:image/png")
    assert "g-seg-b-2" in {g["id"] for g in c["grafici"]}


def test_kit(con):
    c = _ctx(con, "kit", candidato="sindaco")
    assert c["n"] == 0 and c["fonti"] == []
    con.execute(
        "INSERT INTO contenuto (candidato, formato, testo, fonti_dati, stato) VALUES "
        "('sindaco', 'post Instagram', 'Testo approvato', '[\"https://x.test\"]', 'approvato'), "
        "('sindaco', 'post Instagram', 'Bozza', NULL, 'bozza')"
    )
    c = _ctx(con, "kit", candidato="sindaco")
    assert c["n"] == 1 and c["gruppi"]["post Instagram"][0]["fonti"] == ["https://x.test"]
    with pytest.raises(dati.ErroreDati):
        _ctx(con, "kit", candidato="nessuno")
