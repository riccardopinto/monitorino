import geopandas as gpd
import pytest
from shapely.geometry import box

from app.core import db
from app.ingest import circoscrizioni as ing

# Origine approssimativa di Torino in Gauss-Boaga fuso Ovest (EPSG:3003)
X0, Y0 = 1_395_000, 4_990_000


def _shapefile(tmp_path, codici=range(1, 9), crs="EPSG:3003"):
    gdf = gpd.GeoDataFrame(
        {"NCIRCO": list(codici), "DENOM": [f"Circ {c}" for c in codici]},
        geometry=[
            box(X0 + i * 1000, Y0, X0 + (i + 1) * 1000, Y0 + 1000) for i in range(len(codici))
        ],
        crs=crs,
    )
    percorso = tmp_path / "circ.shp"
    gdf.to_file(percorso)
    return percorso


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    yield c
    c.close()


def test_lettura_e_conversione_wgs84(tmp_path):
    gdf = ing.leggi(_shapefile(tmp_path))
    assert list(gdf["codice"]) == [str(n) for n in range(1, 9)]
    assert gdf.crs.to_string() == "EPSG:4326"
    lon, lat = gdf.geometry.iloc[0].centroid.coords[0]
    assert 7.5 < lon < 7.9 and 44.9 < lat < 45.2


def test_rifiuta_circoscrizioni_mancanti(tmp_path):
    with pytest.raises(ing.ErroreIngest):
        ing.leggi(_shapefile(tmp_path, codici=range(1, 8)))


def test_rifiuta_crs_inatteso(tmp_path):
    with pytest.raises(ing.ErroreIngest):
        ing.leggi(_shapefile(tmp_path, crs="EPSG:32632"))


def test_scrittura_idempotente(tmp_path, con):
    gdf = ing.leggi(_shapefile(tmp_path))
    ing.scrivi(con, gdf)
    ing.scrivi(con, gdf)
    n, codici = con.execute(
        "SELECT count(*), list(codice ORDER BY codice) FROM area WHERE tipo = 'circoscrizione'"
    ).fetchone()
    assert n == 8
    assert sorted(codici, key=int) == [str(i) for i in range(1, 9)]
    assert not db.dati_di_prova(con)
