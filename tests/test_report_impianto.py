import base64

import pytest
from shapely.geometry import box

from app.core import db
from app.reports import fonti, genera, mappe


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    for i, codice in enumerate(("1", "2", "3")):
        c.execute(
            "INSERT INTO area (tipo, codice, nome, geometria) "
            "VALUES ('circoscrizione', ?, ?, ST_GeomFromText(?))",
            [codice, f"Zona {codice}", box(7.6 + i * 0.02, 45.0, 7.62 + i * 0.02, 45.02).wkt],
        )
    c.executemany(
        "INSERT INTO caricamento (fonte, righe, di_prova) VALUES (?, 10, false)",
        [("elezioni:comunali_2021",), ("elezioni:europee_2024",), ("comune_demografia",)],
    )
    yield c
    c.close()


def test_formati_italiani():
    assert genera.num(1234.56) == "1 234,6"
    assert genera.segno(-3.25, 2) == "−3,25" and genera.segno(2) == "+2,0"
    assert genera.num(None) == "–"
    assert genera.data_it("2026-11-17") == "17 novembre 2026"


def test_fonti(con):
    righe = fonti.elenco(con, ["elezioni:*", "comune_demografia", "mef_redditi"])
    assert [r["dato"] for r in righe] == [
        "Risultati elettorali per sezione",
        "Popolazione per circoscrizione, età, sesso, cittadinanza",
    ]  # mef non caricato: non compare
    assert righe[0]["dettaglio"] == "comunali_2021, europee_2024"


def test_classi_come_dashboard():
    limiti, colori = mappe.classi([0, 60], False)
    assert colori == mappe.SEQUENZIALE and limiti[0] == 10
    limiti, colori = mappe.classi([-7, 3.5], True)
    assert colori == mappe.DIVERGENTE and limiti[2] == pytest.approx(-1.0)
    assert mappe.colore_di(limiti, colori, 0) == "#ededed"


def test_mappe_png(con):
    for uri in (
        mappe.coropletica(con, {"1": 10.0, "2": 20.0, "3": None}),
        mappe.coropletica(con, {"1": -5.0, "2": 5.0, "3": 0.0}, divergente=True),
        mappe.evidenzia(con, "2"),
    ):
        assert uri.startswith("data:image/png;base64,")
        assert base64.b64decode(uri.split(",", 1)[1])[:4] == b"\x89PNG"


def test_conta_pagine():
    assert genera.conta_pagine(b"<< /Type /Pages >> << /Type /Page >> <</Type/Page>>") == 2


def test_stampa_e_archivio(con, tmp_path):
    pagina = (
        "<html><body><p>Prova</p><p style='page-break-before: always'>Due</p>"
        "<script>window.__renderFatto = true;</script></body></html>"
    )
    try:
        pdf = genera.stampa(pagina, {"titolo": "Prova", "dati_di_prova": True})
    except genera.ErroreReport as e:
        pytest.skip(str(e))
    assert pdf.contenuto[:4] == b"%PDF" and pdf.pagine == 2
    esito = genera.archivia(con, tipo="scheda", titolo="Scheda prova", parametri={"area": "3"},
                            autore="Staff", pdf=pdf, cartella=tmp_path)  # fmt: skip
    assert (tmp_path / esito["file"]).read_bytes()[:4] == b"%PDF"
    assert con.execute("SELECT titolo, pagine FROM report").fetchone() == ("Scheda prova", 2)
