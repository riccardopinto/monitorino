import pandas as pd
import pytest
from shapely.geometry import box

from app.core import db
from app.ingest import demografia_comune as dc

INTESTAZIONE = (
    '"eta_annuale";"circ_1";"Circ_2";"circ_3";"circ_4";"circ_5";"circ_6";"circ_7";"circ_8";'
    '"residenza_virtuale"\r\n'
)


def _f(prefisso, forma="matrice", eta=False):
    return dc.FileComune("x", "x.csv", forma, prefisso, eta)


def test_matrice_per_eta():
    dati = (INTESTAZIONE + "0;1;2;3;4;5;6;7;8;9\r\n101;0;0;1;0;0;0;0;0;0\r\n").encode()
    t = dc.leggi(_f("pop", eta=True), dati)
    assert set(t.variabile) == {"pop_eta_000", "pop_eta_101"}
    assert t[(t.area == "virtuale") & (t.variabile == "pop_eta_000")].valore.item() == 9
    assert t[(t.area == "2") & (t.variabile == "pop_eta_000")].valore.item() == 2


def test_matrice_per_voce():
    dati = (
        INTESTAZIONE.replace("eta_annuale", "tipologia")
        + '"Coppie con figli";1;1;1;1;1;1;1;1;0\r\n'
    ).encode()
    t = dc.leggi(_f("famiglie"), dati)
    assert set(t.variabile) == {"famiglie_coppie_con_figli"}
    assert len(t) == 9


def test_per_circoscrizione_con_totale():
    dati = b'"circoscrizione ";"femmine";"maschi";\r\n1;4;6;10\r\n"Residenza virtuale";1;2;3\r\n'
    t = dc.leggi(_f("stranieri", "per_circoscrizione"), dati).set_index(["area", "variabile"])
    assert t.loc[("1", "stranieri"), "valore"] == 10
    assert t.loc[("virtuale", "stranieri_m"), "valore"] == 2


def test_totale_incoerente():
    dati = b'"circoscrizione ";"femmine";"maschi";\r\n1;4;6;11\r\n'
    with pytest.raises(dc.ErroreIngest):
        dc.leggi(_f("stranieri", "per_circoscrizione"), dati)


def _tutto(m_extra=0):
    righe = []
    for area in ["1", "virtuale"]:
        righe += [
            (area, "pop_eta_000", 10.0),
            (area, "pop_m_eta_000", 4.0 + m_extra),
            (area, "pop_f_eta_000", 6.0),
            (area, "genere_m", 4.0),
            (area, "genere_f", 6.0),
            (area, "stranieri_eta_000", 2.0),
            (area, "stranieri", 2.0),
        ]
    return pd.DataFrame(righe, columns=["area", "variabile", "valore"])


def test_controlli():
    dc.controlla(_tutto())
    with pytest.raises(dc.ErroreIngest):
        dc.controlla(_tutto(m_extra=1))


def test_scrittura(tmp_path):
    con = db.connetti(tmp_path / "d.duckdb")
    db.crea_schema(con)
    for i in range(1, 9):
        con.execute(
            "INSERT INTO area (tipo, codice, geometria) "
            "VALUES ('circoscrizione', ?, ST_GeomFromWKB(?))",
            [str(i), box(0, 0, 1, 1).wkb],
        )
    dc.scrivi(con, _tutto())
    dc.scrivi(con, _tutto())  # idempotente
    righe = con.execute(
        "SELECT area_id, variabile, valore FROM demografia ORDER BY 1, 2"
    ).fetchall()
    assert (-1, "pop_eta_000", 10.0) in righe
    assert not any(v.startswith("genere") for _, v, _ in righe)
    assert len(righe) == 10
    con.close()
