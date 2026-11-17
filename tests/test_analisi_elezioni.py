from datetime import date

import numpy as np
import pytest

from app.analysis import elezioni as an
from app.core import db


def test_stima_flussi_ritrova_matrice_nota():
    rng = np.random.default_rng(0)
    vera = np.array(
        [
            [0.80, 0.10, 0.10],
            [0.05, 0.70, 0.25],
            [0.10, 0.20, 0.70],
        ]
    )
    x = rng.dirichlet([4, 3, 3], size=400)
    y = x @ vera + rng.normal(0, 0.005, size=(400, 3))
    y = np.clip(y, 0, None)
    y = y / y.sum(axis=1, keepdims=True)
    b, r2 = an.stima_flussi(x, y, np.full(400, 800.0))
    assert np.abs(b - vera).max() < 0.03
    assert np.allclose(b.sum(axis=1), 1)
    assert (b >= 0).all()
    assert (r2 > 0.8).all()


def _elezione(con, eid, data, liste, sezioni):
    """liste: {nome: area}; sezioni: {sezione: (elettori, {lista: voti})}."""
    con.execute(
        "INSERT INTO elezione (id, tipo, data, turno, nome) VALUES (?, 'europee', ?, 1, ?)",
        [eid, data, f"E{eid}"],
    )
    for nome, area in liste.items():
        con.execute(
            "INSERT INTO lista_alias VALUES (?, 'lista', ?, ?, ?, NULL)", [eid, nome, nome, area]
        )
    for sez, (elettori, voti) in sezioni.items():
        con.execute(
            "INSERT INTO affluenza (elezione_id, sezione, elettori, votanti) VALUES (?, ?, ?, ?)",
            [eid, sez, elettori, sum(voti.values())],
        )
        for lista, v in voti.items():
            con.execute(
                "INSERT INTO risultato (elezione_id, sezione, tipo_soggetto, soggetto, voti) "
                "VALUES (?, ?, 'lista', ?, ?)",
                [eid, sez, lista, v],
            )
        con.execute(
            "INSERT OR REPLACE INTO sezione_area VALUES (?, ?, ?)",
            [sez, data.year, "1" if int(sez) <= 2 else "2"],
        )


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "a.duckdb")
    db.crea_schema(c)
    _elezione(
        c,
        1,
        date(2021, 1, 1),
        {"A": "centrosinistra", "B": "centrodestra"},
        {
            "1": (100, {"A": 40, "B": 20}),
            "2": (100, {"A": 30, "B": 30}),
            "3": (200, {"A": 50, "B": 100}),
        },
    )
    _elezione(
        c,
        2,
        date(2024, 1, 1),
        {"A2": "centrosinistra", "C": "centrodestra"},
        {
            "1": (100, {"A2": 30, "C": 30}),
            "2": (100, {"A2": 30, "C": 30}),
            "3": (200, {"A2": 60, "C": 60}),
        },
    )
    yield c
    c.close()


def test_risultati_per_livello(con):
    citta = an.risultati(con, 1, "citta", "lista").set_index("soggetto")
    assert citta.loc["A", "voti"] == 120 and citta.loc["B", "voti"] == 150
    assert citta["quota"].sum() == pytest.approx(1)
    circ = an.risultati(con, 1, "circoscrizione", "area")
    c1 = circ[circ.area == "1"].set_index("soggetto")
    assert c1.loc["centrosinistra", "voti"] == 70
    assert c1.loc["centrosinistra", "quota"] == pytest.approx(70 / 120)


def test_affluenza(con):
    a = an.affluenza(con, 1, "circoscrizione").set_index("area")
    assert a.loc["1", "elettori"] == 200 and a.loc["1", "votanti"] == 120
    assert a.loc["2", "affluenza"] == pytest.approx(150 / 200)


def test_variazione_su_area_politica(con):
    v = an.variazione(con, 1, 2, "citta", "area").set_index("soggetto")
    # centrosinistra: 120/270 -> 120/240
    assert v.loc["centrosinistra", "variazione_punti"] == pytest.approx(
        (120 / 240 - 120 / 270) * 100
    )


def test_flussi_richiedono_abbastanza_sezioni(con):
    with pytest.raises(ValueError, match="poche sezioni"):
        an.flussi(con, 1, 2)
