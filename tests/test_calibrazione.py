import json
from datetime import date

import pytest

from app.analysis import calibrazione as cal
from app.core import db


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    totale = {"favorevoli_pct": 40.0, "avvicina_pct": 20.0, "allontana_pct": 10.0, "saldo": 10.0}
    aggregati = {"a": {"totale": totale, "aree": [{"area": "3", **totale, "favorevoli_pct": 50.0}]}}
    for stato in ("completata", "in_attesa"):
        c.execute(
            "INSERT INTO simulazione (proposta, risultati, stato) VALUES ('Parco', ?, ?)",
            [json.dumps({"aggregati": aggregati}), stato],
        )
    yield c
    c.close()


def test_senza_calibrazioni(con):
    a = cal.affidabilita(con)
    assert a["n"] == 0 and "non stimata" in a["testo"]


def test_registra_e_indice(con):
    r = cal.registra(con, simulazione_id=1, fonte_sondaggio="Istituto X", metrica="favorevoli_pct",
                     valore_reale=46.0, data_sondaggio=date(2026, 11, 1))  # fmt: skip
    assert r == {"valore_simulato": 40.0, "valore_reale": 46.0, "scarto": -6.0}
    a = cal.affidabilita(con)
    assert a["n"] == 1 and a["scarto_medio"] == 6.0 and a["giudizio"] is None
    assert "troppo pochi" in a["testo"] and "sottostimano" in a["testo"]
    cal.registra(con, simulazione_id=1, fonte_sondaggio="Y", metrica="saldo", valore_reale=8.0)
    cal.registra(con, simulazione_id=1, fonte_sondaggio="Z", metrica="favorevoli_pct",
                 valore_reale=49.0, area="3")  # fmt: skip
    a = cal.affidabilita(con)
    # scarti −6, +2, +1: medio assoluto 3, giudizio buona
    assert a["scarto_medio"] == 3.0 and a["giudizio"] == "buona"
    assert cal.elenco(con, 1)[0]["fonte_sondaggio"] == "Istituto X"


def test_validazioni(con):
    with pytest.raises(cal.ErroreCalibrazione, match="non è completa"):
        cal.registra(con, simulazione_id=2, fonte_sondaggio="X", metrica="saldo", valore_reale=1)
    with pytest.raises(cal.ErroreCalibrazione, match="Metrica"):
        cal.registra(con, simulazione_id=1, fonte_sondaggio="X", metrica="gradimento_medio",
                     valore_reale=3)  # fmt: skip
    with pytest.raises(cal.ErroreCalibrazione, match="fuori scala"):
        cal.registra(con, simulazione_id=1, fonte_sondaggio="X", metrica="favorevoli_pct",
                     valore_reale=120)  # fmt: skip
    with pytest.raises(cal.ErroreCalibrazione, match="variante B"):
        cal.registra(con, simulazione_id=1, fonte_sondaggio="X", metrica="saldo", valore_reale=1,
                     variante="b")  # fmt: skip
    with pytest.raises(cal.ErroreCalibrazione, match="fonte"):
        cal.registra(con, simulazione_id=1, fonte_sondaggio=" ", metrica="saldo", valore_reale=1)
