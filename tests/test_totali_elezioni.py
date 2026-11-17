"""Controlli sui dati elettorali: classificazione, totali ufficiali, coerenza per circoscrizione.

I test sul database reale (data/campagna.duckdb) si saltano se i dati non sono caricati o se
il database è aperto da un altro processo (per esempio l'app in sviluppo).
"""

from datetime import date

import duckdb
import pandas as pd
import pytest

from app.core import config, db
from app.ingest.elezioni import eligendo
from app.ingest.elezioni.carica import ErroreIngest, alias
from app.ingest.elezioni.consultazioni import CONSULTAZIONI, Consultazione

# --- configurazione ---------------------------------------------------------


def test_aree_politiche_valide_e_allineate_ai_segmenti():
    aree = config.aree_politiche()
    da_segmenti = {a for a in config.segmenti().area_di_voto if a != "astensione abituale"}
    assert set(aree.aree) == da_segmenti | {"altro"}
    for c in CONSULTAZIONI:
        _, liste = aree.risolvi(c.chiave)
        assert liste or c.chiave.endswith("ballottaggio"), c.chiave


def test_ereditarieta():
    aree = config.aree_politiche()
    _, base = aree.risolvi("comunali_2021")
    _, circ = aree.risolvi("circoscrizionali_2021")
    assert set(base) < set(circ)
    assert circ["MOVIMENTO 5 STELLE 2050"].area == "M5S"


def test_lista_senza_classificazione_ferma_ingest():
    c = Consultazione("europee_2024", "europee", date(2024, 6, 9), 1, "x", "x")
    risultati = pd.DataFrame(
        {"tipo_soggetto": ["lista", "lista"], "soggetto": ["PARTITO DEMOCRATICO", "NUOVA"]}
    )
    with pytest.raises(ErroreIngest, match="NUOVA"):
        alias(c, risultati, config.aree_politiche())


# --- Eligendo ---------------------------------------------------------------


def test_totali_comunali_per_turno():
    f = eligendo.FORMATI["comunali_2016"]
    righe = [
        {
            "TURNO": "1",
            "ELETTORI": "10",
            "VOTANTI": "6",
            "SCHEDE_BIANCHE": "1",
            "COGNOME": "ROSSI",
            "NOME": "ANNA",
            "VOTI_CANDIDATO": "4",
            "LISTA": "A",
            "VOTI_LISTA": "3",
        },
        {
            "TURNO": "1",
            "ELETTORI": "10",
            "VOTANTI": "6",
            "SCHEDE_BIANCHE": "1",
            "COGNOME": "ROSSI",
            "NOME": "ANNA",
            "VOTI_CANDIDATO": "4",
            "LISTA": "B",
            "VOTI_LISTA": "1",
        },
        {
            "TURNO": "2",
            "ELETTORI": "10",
            "VOTANTI": "5",
            "SCHEDE_BIANCHE": "0",
            "COGNOME": "ROSSI",
            "NOME": "ANNA",
            "VOTI_CANDIDATO": "5",
            "LISTA": "A",
            "VOTI_LISTA": "3",
        },
    ]
    t = eligendo.totali(f, righe)
    assert ("iscritti", "", 10) in t and ("votanti", "", 6) in t
    assert ("lista", "A", 3) in t and ("lista", "B", 1) in t
    assert ("candidato", "ROSSI ANNA", 4) in t


def test_totali_politiche_sommano_i_collegi():
    f = eligendo.FORMATI["camera_2022"]
    righe = [
        {
            "COLLUNINOM": "U01",
            "ELETTORITOT": "100",
            "VOTANTITOT": "60",
            "SKBIANCHE": "1",
            "DESCRLISTA": "PD",
            "VOTILISTA": "20",
            "COGNOME": "A",
            "NOME": "B",
            "VOTICANDIDATO": "30",
        },
        {
            "COLLUNINOM": "U01",
            "ELETTORITOT": "100",
            "VOTANTITOT": "60",
            "SKBIANCHE": "1",
            "DESCRLISTA": "AVS",
            "VOTILISTA": "10",
            "COGNOME": "A",
            "NOME": "B",
            "VOTICANDIDATO": "30",
        },
        {
            "COLLUNINOM": "U02",
            "ELETTORITOT": "50",
            "VOTANTITOT": "40",
            "SKBIANCHE": "2",
            "DESCRLISTA": "PD",
            "VOTILISTA": "15",
            "COGNOME": "C",
            "NOME": "D",
            "VOTICANDIDATO": "15",
        },
    ]
    t = eligendo.totali(f, righe)
    assert ("iscritti", "", 150) in t and ("votanti", "", 100) in t and ("bianche", "", 3) in t
    assert ("lista", "PD", 35) in t and ("lista", "AVS", 10) in t
    assert ("candidato", "A B", 30) in t and ("candidato", "C D", 15) in t


def test_solo_scostamenti_documentati_passano():
    diff = {"votanti": {"ufficiale": 10, "sezioni": 11}}
    assert eligendo.non_previste(diff, {"votanti": {"ufficiale": 10, "sezioni": 11}}) == []
    assert eligendo.non_previste(diff, {})
    assert eligendo.non_previste(diff, {"votanti": {"ufficiale": 10, "sezioni": 12}})


# --- database reale ---------------------------------------------------------


@pytest.fixture(scope="module")
def reale():
    try:
        con = db.connetti(config.impostazioni().db_path, sola_lettura=True)
    except (duckdb.Error, OSError, ValueError) as e:
        pytest.skip(f"database reale non disponibile: {e}")
    if not con.execute("SELECT count(*) FROM elezione").fetchone()[0]:
        pytest.skip("elezioni non caricate")
    yield con
    con.close()


def test_totali_uguali_ai_dati_ufficiali(reale):
    noti = config.scostamenti_noti()
    for c in CONSULTAZIONI:
        riga = reale.execute(
            "SELECT id FROM elezione WHERE tipo = ? AND data = ? AND turno = ?",
            [c.tipo, c.data, c.turno],
        ).fetchone()
        assert riga, f"{c.chiave} non caricata"
        diff = eligendo.differenze(reale, riga[0])
        assert eligendo.non_previste(diff, noti.get(c.chiave, {})) == [], c.chiave


def test_ogni_sezione_ha_circoscrizione_nell_anno(reale):
    senza = reale.execute(
        "SELECT e.nome, a.sezione FROM affluenza a JOIN elezione e ON e.id = a.elezione_id "
        "LEFT JOIN sezione_area s ON s.sezione = a.sezione AND s.anno = year(e.data) "
        "WHERE s.circoscrizione IS NULL LIMIT 5"
    ).fetchall()
    assert senza == []


def test_somma_per_circoscrizione_uguale_al_totale_cittadino(reale):
    righe = reale.execute(
        """
        WITH per_circ AS (
            SELECT r.elezione_id, r.tipo_soggetto, r.soggetto, s.circoscrizione,
                   sum(r.voti) AS voti
            FROM risultato r JOIN elezione e ON e.id = r.elezione_id
            JOIN sezione_area s ON s.sezione = r.sezione AND s.anno = year(e.data)
            WHERE r.tipo_soggetto <> 'preferenza'
            GROUP BY ALL
        ), citta AS (
            SELECT elezione_id, tipo_soggetto, soggetto, sum(voti) AS voti
            FROM risultato WHERE tipo_soggetto <> 'preferenza' GROUP BY ALL
        )
        SELECT c.elezione_id, c.soggetto, c.voti, sum(p.voti)
        FROM citta c JOIN per_circ p USING (elezione_id, tipo_soggetto, soggetto)
        GROUP BY ALL HAVING sum(p.voti) <> c.voti
        """
    ).fetchall()
    assert righe == []


def test_tutte_le_liste_classificate(reale):
    senza = reale.execute(
        "SELECT DISTINCT r.elezione_id, r.soggetto FROM risultato r "
        "LEFT JOIN lista_alias a ON a.elezione_id = r.elezione_id AND a.tipo = 'lista' "
        "AND a.soggetto = r.soggetto WHERE r.tipo_soggetto = 'lista' AND a.soggetto IS NULL"
    ).fetchall()
    assert senza == []
