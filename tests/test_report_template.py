"""Rendering dei cinque template e stampa PDF reale (saltata se manca il browser)."""

import pytest

from app.core import db
from app.llm import simulazione as sim
from app.reports import dati, genera
from tests.test_report_dati import popola
from tests.test_simulazione import SEGMENTI, _risposta_blocco

DICITURA = "Simulazione IA, non è un sondaggio"


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "r.duckdb")
    db.crea_schema(c)
    popola(c)
    r = sim.Richiesta(
        proposta="Un parco",
        candidato="sindaco",
        aree=["1", "2"],
        segmenti=SEGMENTI,
        persone=3,
        seed=1,
        proposta_b="Un parco grande",
    )
    sid = sim.crea(c, r, "chat")
    run = sim.carica(c, sid)
    for b in run["parametri"]["blocchi"]:
        sim.importa_chat(c, sid, b["n"], _risposta_blocco(run, b["n"], con_b=True))
    yield c
    c.close()


CASI = [
    ("scheda", {"area": "1"}, ["Profilo demografico", "Storico elettorale", "inferenza ecologica"]),
    ("confronto", {"modo": "elezioni", "da": 1, "a": 2}, ["Flussi stimati", "Variazione"]),
    ("confronto", {"modo": "aree", "elezione": 1, "area1": "1", "area2": "2"},
     ["Profilo demografico a confronto"]),
    ("bollettino", {}, ["Temi per circoscrizione", "Code in corso"]),
    ("simulazione", {"simulazione": 1}, [DICITURA, "Confronto A/B", "persone sintetiche"]),
    ("kit", {"candidato": "sindaco"}, ["Nessun contenuto approvato", "2024/900"]),
]  # fmt: skip


@pytest.mark.parametrize(("tipo", "parametri", "attesi"), CASI)
def test_html(con, tipo, parametri, attesi):
    ctx = dati.contesto(con, tipo, parametri, autore="Staff", versione="0.1.0")
    pagina = genera.html(tipo, ctx)
    for testo in [*attesi, "Fonti e date dei dati", "Staff"]:
        assert testo in pagina, testo
    assert "window.__renderFatto" in pagina
    if ctx["grafici"]:
        assert "Chart" in pagina  # Chart.js incluso nella pagina, nessuna richiesta esterna
    assert "http://" not in pagina.replace("http://www.w3.org", "")


def test_dati_di_prova_in_copertina(con):
    con.execute("INSERT INTO caricamento (fonte, righe, di_prova) VALUES ('fixture', 1, true)")
    ctx = dati.contesto(con, "kit", {"candidato": "sindaco"})
    assert "DATI DI PROVA" in genera.html("kit", ctx)


@pytest.mark.parametrize(("tipo", "parametri", "attesi"), [CASI[0], CASI[4]])
def test_pdf(con, tipo, parametri, attesi):
    ctx = dati.contesto(con, tipo, parametri, autore="Staff", versione="0.1.0")
    try:
        pdf = genera.stampa(genera.html(tipo, ctx), ctx)
    except genera.ErroreReport as e:
        pytest.skip(str(e))
    assert pdf.contenuto[:4] == b"%PDF" and pdf.pagine >= 3
    assert pdf.durata_s < 30
