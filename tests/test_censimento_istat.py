import io
import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from app.core import db
from app.ingest import censimento_istat as ci


def _zip_dati(tmp_path, righe):
    df = pd.DataFrame(righe)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    p = tmp_path / "dati.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("R01_indicatori_2021_sezioni.xlsx", buf.getvalue())
    return p


def _riga(sez, circ, pop, procom=1272):
    r = {c: 0 for c in ci.VARIABILI}
    r.update({"PROCOM": procom, "SEZ21_ID": sez, "COM_ASC1": 1272000 + circ, "P1": pop})
    r["P90"] = pop // 4
    return r


def test_lettura_filtra_torino_e_circoscrizione(tmp_path):
    p = _zip_dati(
        tmp_path,
        [_riga(12720000001, 1, 100), _riga(12720000002, 8, 50), _riga(10010000001, 1, 7, 1001)],
    )
    s = ci.leggi_sezioni(p)
    assert len(s) == 2
    assert s.set_index("SEZ21_ID").loc[12720000002, "circoscrizione"] == "8"
    assert s["cens_istr_terziario"].sum() == 25 + 12


def test_variabile_mancante(tmp_path):
    r = _riga(12720000001, 1, 100)
    del r["P101"]
    with pytest.raises(ci.ErroreIngest):
        ci.leggi_sezioni(_zip_dati(tmp_path, [r]))


def test_assegnazione_alle_sezioni_elettorali():
    # Due sezioni elettorali affiancate, tre sezioni di censimento (una fuori dai confini).
    elettorali = gpd.GeoDataFrame(
        {"codice": ["10", "11"]},
        geometry=[box(7.60, 45.00, 7.61, 45.01), box(7.61, 45.00, 7.62, 45.01)],
        crs="EPSG:4326",
    )
    censimento = gpd.GeoDataFrame(
        {"SEZ21_ID": [1, 2, 3]},
        geometry=[
            box(7.601, 45.001, 7.602, 45.002),
            box(7.615, 45.001, 7.616, 45.002),
            box(7.6205, 45.011, 7.621, 45.012),  # appena fuori: va alla più vicina
        ],
        crs="EPSG:4326",
    ).to_crs(32632)
    a = ci.assegna_sezioni_elettorali(censimento, elettorali)
    assert a.to_dict() == {1: "10", 2: "11", 3: "11"}


def test_tavole_comunali(tmp_path):
    cond = tmp_path / "c.csv"
    cond.write_text(
        "GENDER,AGE_NOCLASS,CUR_ACT_STAT,TIME_PERIOD,OBS_VALUE\n"
        "T,Y15-24,5,2023,10\nT,Y15-24,5,2024,12\nM,Y15-24,5,2024,6\nT,Y_GE15,5,2024,99\n",
        encoding="utf-8",
    )
    pos = tmp_path / "p.csv"
    pos.write_text(
        "GENDER,EMPLOYMENT_STATUS,TIME_PERIOD,OBS_VALUE\nT,9,2021,75\nT,22,2021,25\n",
        encoding="utf-8",
    )
    t = ci.tavole_comunali(cond, pos).set_index("variabile")
    assert t.loc["istat_cond_studente_eta_15_24", "valore"] == 12  # anno più recente, totale
    assert t.loc["istat_cond_studente_eta_15_24", "anno"] == 2024
    assert t.loc["istat_occupati_indipendenti", "valore"] == 25


def test_scrittura(tmp_path):
    con = db.connetti(tmp_path / "c.duckdb")
    db.crea_schema(con)
    con.execute("INSERT INTO area (id, tipo, codice) VALUES (1, 'circoscrizione', '1')")
    con.execute("INSERT INTO area (id, tipo, codice) VALUES (50, 'sezione', '10')")
    sezioni = pd.DataFrame([_riga(1, 1, 100), _riga(2, 1, 30)]).rename(columns=ci.VARIABILI)
    sezioni["circoscrizione"] = "1"
    elettorale = pd.Series({1: "10", 2: "10"})
    comunali = pd.DataFrame(
        [("istat_occupati_totale", 2021, 10.0)], columns=["variabile", "anno", "valore"]
    )
    ci.scrivi(con, sezioni, elettorale, comunali)
    ci.scrivi(con, sezioni, elettorale, comunali)
    pop = dict(
        con.execute(
            "SELECT area_id, valore FROM demografia WHERE variabile = 'cens_pop'"
        ).fetchall()
    )
    assert pop == {1: 130.0, 50: 130.0}
    assert (
        con.execute(
            "SELECT valore FROM demografia "
            "WHERE area_id = 0 AND variabile = 'istat_occupati_totale'"
        ).fetchone()[0]
        == 10.0
    )
    con.close()
