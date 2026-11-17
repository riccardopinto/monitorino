import pandas as pd
import pytest

from app.analysis import demografia as dm
from app.core import db


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "dm.duckdb")
    db.crea_schema(c)
    c.execute(
        "INSERT INTO area (id, tipo, codice) "
        "VALUES (1, 'circoscrizione', '1'), (2, 'circoscrizione', '2')"
    )
    righe = [
        # Comune: età 10 (giovane) e 70 (anziano), più residenza virtuale
        (1, "pop_eta_010", 10), (1, "pop_eta_070", 30), (1, "stranieri", 4),
        (2, "pop_eta_010", 20), (2, "pop_eta_070", 20), (2, "stranieri", 8),
        (-1, "pop_eta_070", 10), (-1, "stranieri", 2),
        (1, "pop_m_eta_010", 4), (1, "pop_f_eta_010", 6), (1, "pop_m_eta_070", 10),
        (1, "pop_f_eta_070", 20),
    ]  # fmt: skip
    c.executemany(
        "INSERT INTO demografia VALUES (?, 2025, ?, ?, ?)",
        [(a, v, x, dm.COMUNE) for a, v, x in righe],
    )
    c.executemany(
        "INSERT INTO demografia VALUES (?, 2024, ?, ?, ?)",
        [
            (1, "mef_reddito_complessivo_eur", 300.0, dm.MEF),
            (1, "mef_reddito_complessivo_n", 10.0, dm.MEF),
            (0, "mef_reddito_complessivo_eur", 1000.0, dm.MEF),
            (0, "mef_reddito_complessivo_n", 40.0, dm.MEF),
        ],
    )
    yield c
    c.close()


def test_indicatori_per_circoscrizione_e_citta(con):
    v = dm.valori(con, "indice_vecchiaia", "circoscrizione").set_index("area")["valore"]
    assert v["1"] == pytest.approx(300) and v["2"] == pytest.approx(100)
    # La città include la residenza virtuale: (30+20+10) / (10+20) * 100
    assert dm.valori(con, "indice_vecchiaia", "citta")["valore"].item() == pytest.approx(200)
    assert dm.valori(con, "quota_stranieri", "citta")["valore"].item() == pytest.approx(
        14 / 90 * 100
    )


def test_reddito_citta_dal_totale_esatto(con):
    assert dm.valori(con, "reddito_medio", "citta")["valore"].item() == 25
    assert dm.valori(con, "reddito_medio", "circoscrizione")["valore"].item() == 30


def test_piramide(con):
    p, fonte, anno = dm.piramide(con, "circoscrizione", "1")
    p = p.set_index("classe")
    assert p.loc["10-14", "maschi"] == 4 and p.loc["70-74", "femmine"] == 20
    assert fonte == dm.COMUNE and anno == 2025


def test_condizioni_per_fascia_ereditano_le_classi_istat():
    tavola = pd.DataFrame(
        {"occupato": [0.2, 0.8, 0.6, 0.0], "in_cerca": [0.1, 0.1, 0.1, 0.0],
         "pensionato": [0.0, 0.0, 0.2, 1.0], "studente": [0.7, 0.05, 0.0, 0.0],
         "casalingo": [0.0, 0.05, 0.1, 0.0]},
        index=["15_24", "25_49", "50_64", "65_piu"],
    )  # fmt: skip
    pop = pd.Series(1.0, index=range(0, 101))
    q = dm.condizioni_per_fascia(tavola, pop, ["18-29", "65+"])
    # 18-29: 7 anni nella classe 15-24 e 5 nella 25-49
    assert q.loc["18-29", "studente"] == pytest.approx((7 * 0.7 + 5 * 0.05) / 12)
    assert q.loc["65+", "pensionato"] == pytest.approx(1)
    assert q.sum(axis=1).tolist() == pytest.approx([1, 1])


def test_aggiustamento_occupazione_conserva_le_righe():
    q = pd.DataFrame({"occupato": [0.6, 0.0], "studente": [0.4, 0.0], "pensionato": [0.0, 1.0]},
                     index=["30-44", "65+"])  # fmt: skip
    a = dm.aggiusta_occupazione(q, 1.1, ["30-44"])
    assert a.loc["30-44", "occupato"] == pytest.approx(0.66)
    assert a.loc["30-44"].sum() == pytest.approx(1)
    assert a.loc["65+"].tolist() == [0.0, 0.0, 1.0]  # fascia non da lavoro invariata


def test_pesi_reali_sommano_a_uno():
    """Sul database reale, se i pesi sono stati calcolati."""
    from app.core.config import impostazioni

    try:
        c = db.connetti(impostazioni().db_path, sola_lettura=True)
    except Exception as e:  # database aperto da un altro processo o assente
        pytest.skip(f"database reale non disponibile: {e}")
    somme = c.execute(
        "SELECT variante, area_id, sum(peso), min(peso) FROM segmento_peso GROUP BY ALL"
    ).fetchall()
    c.close()
    if not somme:
        pytest.skip("pesi non calcolati")
    for variante, area, totale, minimo in somme:
        assert totale == pytest.approx(1, abs=1e-9), (variante, area)
        assert minimo >= 0
    assert {s[0] for s in somme} == {"comunali", "nazionali"}
