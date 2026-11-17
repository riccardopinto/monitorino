import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from app.ingest import redditi_mef as rm


def _geometrie():
    # Tre sezioni di censimento: 1 e 2 affiancate, 3 senza civici al suo interno.
    return gpd.GeoDataFrame(
        {"SEZ21_ID": [1, 2, 3]},
        geometry=[
            box(7.600, 45.000, 7.610, 45.010),
            box(7.610, 45.000, 7.620, 45.010),
            box(7.620, 45.000, 7.630, 45.010),
        ],
        crs="EPSG:4326",
    ).to_crs(32632)


def _civici():
    # Sezione 1: tre civici CAP A e uno CAP B; sezione 2: due civici CAP B.
    return pd.DataFrame(
        {
            "cap": ["A", "A", "A", "B", "B", "B"],
            "lon": [7.601, 7.602, 7.603, 7.604, 7.611, 7.618],
            "lat": [45.001, 45.002, 45.003, 45.004, 45.005, 45.006],
        }
    )


def test_popolazione_per_cap():
    pop = pd.Series({1: 400.0, 2: 100.0, 3: 50.0})
    p = rm.popolazione_per_cap(_civici(), _geometrie(), pop)
    per = p.groupby(["SEZ21_ID", "cap"])["pop"].sum()
    assert per[(1, "A")] == pytest.approx(300)
    assert per[(1, "B")] == pytest.approx(100)
    assert per[(2, "B")] == pytest.approx(100)
    assert per[(3, "B")] == pytest.approx(50)  # nessun civico: CAP del più vicino
    assert p["pop"].sum() == pytest.approx(550)


def test_ripartizione_conserva_i_totali():
    pop = pd.Series({1: 400.0, 2: 100.0, 3: 50.0})
    p = rm.popolazione_per_cap(_civici(), _geometrie(), pop)
    redditi = pd.DataFrame(
        {"mef_contribuenti": [300.0, 250.0], "mef_reddito_complessivo_eur": [9e6, 5e6]},
        index=pd.Index(["A", "B"], name="CAP"),
    )
    area = pd.Series({1: "1", 2: "2", 3: "2"})
    r = rm.ripartisci(redditi, p, area).pivot(index="area", columns="variabile", values="valore")
    assert r["mef_contribuenti"].sum() == pytest.approx(550)
    # CAP A tutto nell'area 1; CAP B: 100 su 250 di popolazione nell'area 1
    assert r.loc["1", "mef_contribuenti"] == pytest.approx(300 + 250 * 100 / 250)


def test_cap_senza_popolazione():
    p = pd.DataFrame({"SEZ21_ID": [1], "cap": ["A"], "pop": [10.0]})
    redditi = pd.DataFrame({"mef_contribuenti": [1.0, 2.0]}, index=pd.Index(["A", "Z"], name="CAP"))
    with pytest.raises(rm.ErroreIngest, match="Z"):
        rm.ripartisci(redditi, p, pd.Series({1: "1"}))
