import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from app.core import db
from app.ingest import sezioni as ing

# Due circoscrizioni quadrate affiancate vicino a Torino (gradi WGS84)
C1 = box(7.60, 45.00, 7.62, 45.02)
C2 = box(7.62, 45.00, 7.64, 45.02)


@pytest.fixture
def circoscrizioni():
    return gpd.GeoDataFrame({"codice": ["1", "2"]}, geometry=[C1, C2], crs="EPSG:4326")


@pytest.fixture
def con(tmp_path, circoscrizioni):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    c.executemany(
        "INSERT INTO area (tipo, codice, nome, geometria) "
        "VALUES ('circoscrizione', ?, ?, ST_GeomFromWKB(?))",
        [(r.codice, f"C{r.codice}", r.geometry.wkb) for r in circoscrizioni.itertuples()],
    )
    yield c
    c.close()


@pytest.mark.parametrize(
    "a, b",
    [
        ("VIA BARBAROUX GIUSEPPE", "Via Giuseppe Barbaroux"),
        ("CORSO VITTORIO EMANUELE II", "corso vittorio emanuele II"),
        ("PIAZZA SAN CARLO", "Piazza  San-Carlo"),
        ("VIA NIZZA", "via Nizzà"),
    ],
)
def test_chiave_via_equivalenti(a, b):
    assert ing.chiave_via(a) == ing.chiave_via(b)


def test_chiave_via_distingue():
    assert ing.chiave_via("VIA NIZZA") != ing.chiave_via("CORSO NIZZA")


@pytest.mark.parametrize(
    "civico, atteso",
    [("28/A", 28), ("63 scala B", 63), ("138 bis/D", 138), (" 7", 7), ("0", None), ("SNC", None)],
)
def test_numero_base(civico, atteso):
    assert ing.numero_base(civico) == atteso


def test_lettura_file(tmp_path):
    seggi = tmp_path / "seggi.csv"
    seggi.write_text(
        "DESCRIZIONE_VIA,NUMERO_CIVICO,BIS/INTERNO/SCALA,CIRCOSCRIZIONE,SEZIONE,"
        "TIPO_FABBRICATO,DENOMINAZ_FABBRICATO,INDIRIZZO,CAP\n"
        "VIA ROMA,10,A,01,007,SC,X,Y,10100\n"
        "SENZA FISSA DIMORA,998,,0,107,SC,X,Y,10100\n",
        encoding="utf-8",
    )
    civici = tmp_path / "civici.csv"
    civici.write_text(
        '"COD_CIVICO","COMUNE","VIA","CIVICO","CIRCOSCRIZIONE","CAP","COORDINATA_X","COORDINATA_Y"\n'
        '1,"Torino","VIA ROMA","10/A",1,10100,"7,61","45,01"\n',
        encoding="utf-8",
    )
    s = ing.leggi_seggi(seggi)
    assert s.to_dict("records") == [
        {"via": "ROMA VIA", "numero": 10, "sezione": "7", "circoscrizione": "1"}
    ]
    c = ing.leggi_civici(civici)
    assert (c.loc[0, "lon"], c.loc[0, "lat"]) == (7.61, 45.01)


def _caso():
    """Sezione 1 e 2 nella circoscrizione 1, sezione 3 nella 2; un civico non abbinabile."""
    seggi = pd.DataFrame(
        {
            "via": ["A", "A", "B", "C", "C", "Z"],
            "numero": [1, 2, 1, 1, 2, 9],
            "sezione": ["1", "1", "2", "3", "3", "3"],
            "circoscrizione": ["1", "1", "1", "2", "2", "2"],
        }
    )
    civici = pd.DataFrame(
        {
            "via": ["A", "A", "B", "C", "C"],
            "numero": [1, 2, 1, 1, 2],
            "lon": [7.605, 7.606, 7.615, 7.625, 7.635],
            "lat": [45.005, 45.015, 45.010, 45.005, 45.015],
        }
    )
    return seggi, civici


def test_abbinamento():
    seggi, civici = _caso()
    abb = ing.abbina(seggi, civici)
    assert (abb.chiavi_abbinate, abb.chiavi_totali) == (5, 6)
    assert sorted(abb.punti["sezione"]) == ["1", "1", "2", "3", "3"]


def test_circoscrizione_di_maggioranza():
    seggi = pd.DataFrame({"sezione": ["5"] * 3, "circoscrizione": ["2", "2", "7"]})
    assert ing.circoscrizione_per_sezione(seggi)["5"] == "2"


def test_voronoi_copre_senza_sovrapposizioni(circoscrizioni):
    seggi, civici = _caso()
    pol = ing.poligoni_sezioni(ing.abbina(seggi, civici).punti, circoscrizioni)
    assert sorted(pol["sezione"]) == ["1", "2", "3"]

    metrico = pol.to_crs(ing.CRS_METRICO).set_index("sezione").geometry
    circ_m = circoscrizioni.to_crs(ing.CRS_METRICO).set_index("codice").geometry
    # ogni sezione sta nella sua circoscrizione
    assert metrico["1"].buffer(-0.01).within(circ_m["1"])
    assert metrico["2"].buffer(-0.01).within(circ_m["1"])
    assert metrico["3"].buffer(-0.01).within(circ_m["2"])
    # le sezioni della circoscrizione 1 la coprono tutta e non si sovrappongono
    assert metrico["1"].intersection(metrico["2"]).area < 1e-3
    assert metrico["1"].union(metrico["2"]).area == pytest.approx(circ_m["1"].area, rel=1e-6)
    assert metrico["3"].area == pytest.approx(circ_m["2"].area, rel=1e-6)


def test_scrittura_idempotente(con, circoscrizioni):
    seggi, civici = _caso()
    pol = ing.poligoni_sezioni(ing.abbina(seggi, civici).punti, circoscrizioni)
    circ = ing.circoscrizione_per_sezione(seggi)
    ing.scrivi(con, pol, circ)
    ing.scrivi(con, pol, circ)

    assert con.execute("SELECT count(*) FROM area WHERE tipo = 'sezione'").fetchone()[0] == 3
    assert con.execute("SELECT bool_and(approssimata) FROM area WHERE tipo = 'sezione'").fetchone()[
        0
    ]
    righe = con.execute(
        "SELECT sezione, anno, circoscrizione FROM sezione_area ORDER BY sezione"
    ).fetchall()
    assert righe == [("1", 2017, "1"), ("2", 2017, "1"), ("3", 2017, "2")]
    # ogni sezione con geometria è figlia della circoscrizione giusta
    errate = con.execute(
        "SELECT count(*) FROM area s JOIN area c ON s.id_padre = c.id "
        "JOIN sezione_area sa ON sa.sezione = s.codice "
        "WHERE s.tipo = 'sezione' AND c.codice <> sa.circoscrizione"
    ).fetchone()[0]
    assert errate == 0
