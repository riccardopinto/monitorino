"""Ingest del censimento permanente ISTAT 2021 per sezione di censimento, e tabelle comunali.

Fonti (ISTAT, licenza CC BY 4.0):
- variabili censuarie per sezione al 31/12/2021: Dati_regionali_2021.zip (file R01 Piemonte);
- basi territoriali 2021 del Piemonte (geometrie delle sezioni): R01_21.zip;
- IstatData, tavole comunali di Torino: condizione professionale per età (2018-2024) e
  occupati per posizione nella professione (2021).

Le sezioni di censimento si aggregano:
- per circoscrizione con il codice ISTAT COM_ASC1 (aree sub-comunali = circoscrizioni);
- per sezione elettorale con il punto interno della sezione di censimento che cade nei
  confini approssimati delle sezioni elettorali (Fase 1).
Le tavole comunali si salvano con area_id = 0 (comune intero).

Uso: ``uv run python -m app.ingest.censimento_istat``
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
from shapely import wkb

from app.core import db
from app.core.config import impostazioni
from app.ingest._comune import DIR_PROCESSED, registra_caricamento, scarica

FONTE = "istat_censimento_2021"
ETICHETTA = "ISTAT, Censimento permanente 2021"
ETICHETTA_COMUNE = "ISTAT, IstatData (tavole comunali)"
ANNO = 2021
PROCOM_TORINO = 1272
AREA_COMUNE = 0

URL_DATI = "https://esploradati.istat.it/databrowser/DWL/PERMPOP/SUBCOM/Dati_regionali_2021.zip"
URL_BASI = "https://www.istat.it/storage/cartografia/basi_territoriali/2021/R01_21.zip"
SDMX = "https://esploradati.istat.it/SDMXWS/rest/data/IT1,{flusso},1.0/A.001272{chiave}"
ACCETTA_CSV = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}

CLASSI = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44",
          "45_49", "50_54", "55_59", "60_64", "65_69", "70_74", "75_piu"]  # fmt: skip

# Codici del tracciato ISTAT -> nome della variabile (prefisso cens_).
VARIABILI = {
    "P1": "cens_pop",
    "P2": "cens_pop_m",
    "P3": "cens_pop_f",
    **{f"P{14 + i}": f"cens_eta_{c}" for i, c in enumerate(CLASSI)},
    **{f"P{30 + i}": f"cens_m_eta_{c}" for i, c in enumerate(CLASSI)},
    **{f"P{67 + i}": f"cens_f_eta_{c}" for i, c in enumerate(CLASSI)},
    "P83": "cens_pop_9piu",
    "P86": "cens_istr_nessuno",
    "P87": "cens_istr_elementare",
    "P88": "cens_istr_media",
    "P89": "cens_istr_diploma",
    "P90": "cens_istr_terziario",
    "P101": "cens_occupati_15_64",
    "ST1": "cens_stranieri",
    "PF1": "cens_famiglie",
    "PF3": "cens_fam_1",
    "PF4": "cens_fam_2",
    "PF5": "cens_fam_3",
    "PF6": "cens_fam_4",
    "PF7": "cens_fam_5",
    "PF8": "cens_fam_6piu",
    "A2": "cens_abitazioni_occupate",
    "A8": "cens_abitazioni",
    "E3": "cens_edifici_residenziali",
}

# Codici IstatData (CL_FORZE_LAV e CL_PROFILO_PROF) -> nome breve.
CONDIZIONI = {
    "1": "occupato",
    "12": "in_cerca",
    "24": "pensionato",
    "5": "studente",
    "4": "casalingo",
    "7": "altra_condizione",
    "99": "totale",
}
POSIZIONI = {"9": "dipendenti", "22": "indipendenti", "99": "totale"}
ETA_ISTAT = {"Y15-24": "15_24", "Y25-49": "25_49", "Y50-64": "50_64", "Y_GE65": "65_piu"}


class ErroreIngest(RuntimeError):
    pass


def leggi_sezioni(percorso_dati: Path) -> pd.DataFrame:
    """Variabili per sezione di censimento di Torino (una riga per sezione abitata)."""
    with zipfile.ZipFile(percorso_dati) as zf:
        df = pd.read_excel(io.BytesIO(zf.read("R01_indicatori_2021_sezioni.xlsx")))
    df = df[df["PROCOM"].astype(int) == PROCOM_TORINO]
    mancanti = set(VARIABILI) - set(df.columns)
    if mancanti:
        raise ErroreIngest(f"Variabili mancanti nel file ISTAT: {sorted(mancanti)}")
    out = df[["SEZ21_ID", "COM_ASC1", *VARIABILI]].rename(columns=VARIABILI)
    out["SEZ21_ID"] = out["SEZ21_ID"].astype("int64")
    out["circoscrizione"] = (out.pop("COM_ASC1").astype(int) - PROCOM_TORINO * 1000).astype(str)
    return out.reset_index(drop=True)


def leggi_geometrie(percorso_basi: Path) -> gpd.GeoDataFrame:
    sorgente = f"/vsizip/{percorso_basi.as_posix()}/SHP/R01_21_WGS84.shp"
    # Senza "columns": con un sottoinsieme di colonne la lettura di questo file restituisce
    # POP21 a zero (verificato con pyogrio); si leggono tutte e si selezionano dopo.
    g = gpd.read_file(sorgente, where=f"PRO_COM = {PROCOM_TORINO}")[
        ["SEZ21_ID", "POP21", "geometry"]
    ]
    g["SEZ21_ID"] = g["SEZ21_ID"].astype("int64")
    return g


def assegna_sezioni_elettorali(
    geometrie: gpd.GeoDataFrame, elettorali: gpd.GeoDataFrame
) -> pd.Series:
    """Sezione elettorale di ogni sezione di censimento (dal suo punto interno)."""
    punti = geometrie[["SEZ21_ID"]].copy()
    punti = gpd.GeoDataFrame(
        punti, geometry=geometrie.geometry.representative_point(), crs=geometrie.crs
    ).to_crs(elettorali.crs)
    unite = gpd.sjoin(punti, elettorali[["codice", "geometry"]], how="left", predicate="within")
    unite = unite[~unite.index.duplicated()]
    # Punti fuori da ogni poligono (bordi del comune): sezione elettorale più vicina.
    fuori = unite["codice"].isna()
    if fuori.any():
        vicine = gpd.sjoin_nearest(
            punti[fuori].to_crs(32632), elettorali[["codice", "geometry"]].to_crs(32632)
        )
        unite.loc[fuori, "codice"] = vicine[~vicine.index.duplicated()]["codice"]
    return unite.set_index("SEZ21_ID")["codice"]


def leggi_sdmx(percorso: Path, mappa_codici: dict[str, str], colonna: str) -> pd.DataFrame:
    d = pd.read_csv(percorso, dtype=str)
    d = d[(d["GENDER"] == "T") & d[colonna].isin(mappa_codici)]
    d["valore"] = d["OBS_VALUE"].astype(float)
    d["voce"] = d[colonna].map(mappa_codici)
    return d


def tavole_comunali(condizione: Path, posizione: Path) -> pd.DataFrame:
    """Righe (variabile, anno, valore) del comune: condizione per età e posizione occupati."""
    c = leggi_sdmx(condizione, CONDIZIONI, "CUR_ACT_STAT")
    c = c[c["AGE_NOCLASS"].isin(ETA_ISTAT)]
    anno_c = c["TIME_PERIOD"].astype(int).max()
    c = c[c["TIME_PERIOD"].astype(int) == anno_c]
    righe = [
        (f"istat_cond_{r.voce}_eta_{ETA_ISTAT[r.AGE_NOCLASS]}", anno_c, r.valore)
        for r in c.itertuples()
    ]
    p = leggi_sdmx(posizione, POSIZIONI, "EMPLOYMENT_STATUS")
    anno_p = p["TIME_PERIOD"].astype(int).max()
    p = p[p["TIME_PERIOD"].astype(int) == anno_p]
    righe += [(f"istat_occupati_{r.voce}", anno_p, r.valore) for r in p.itertuples()]
    if not righe:
        raise ErroreIngest("Tavole comunali IstatData vuote")
    return pd.DataFrame(righe, columns=["variabile", "anno", "valore"])


def _lungo(df: pd.DataFrame, chiave: str) -> pd.DataFrame:
    valori = [v for v in VARIABILI.values()]
    return (
        df.groupby(chiave)[valori]
        .sum()
        .reset_index()
        .melt(id_vars=chiave, var_name="variabile", value_name="valore")
    )


def scrivi(
    con: duckdb.DuckDBPyConnection,
    sezioni: pd.DataFrame,
    elettorale: pd.Series,
    comunali: pd.DataFrame,
) -> dict[str, int]:
    circ_ids = dict(
        con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall()
    )
    sez_ids = dict(con.execute("SELECT codice, id FROM area WHERE tipo = 'sezione'").fetchall())
    per_circ = _lungo(sezioni, "circoscrizione")
    per_circ["area_id"] = per_circ["circoscrizione"].map(circ_ids)
    s = sezioni.assign(sezione=sezioni["SEZ21_ID"].map(elettorale))
    per_sez = _lungo(s.dropna(subset=["sezione"]), "sezione")
    per_sez["area_id"] = per_sez["sezione"].map(sez_ids)
    if per_circ["area_id"].isna().any():
        raise ErroreIngest("Circoscrizioni ISTAT senza corrispondenza in area")
    dati = pd.concat(
        [per_circ[["area_id", "variabile", "valore"]], per_sez[["area_id", "variabile", "valore"]]]
    ).dropna(subset=["area_id"])
    dati = dati.assign(anno=ANNO, fonte=ETICHETTA)
    com = comunali.assign(area_id=AREA_COMUNE, fonte=ETICHETTA_COMUNE)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM demografia WHERE fonte IN (?, ?)", [ETICHETTA, ETICHETTA_COMUNE])
        for nome, tab in (("_cens", dati), ("_com", com)):
            con.register(nome, tab)
            con.execute(
                "INSERT INTO demografia (area_id, anno, variabile, valore, fonte) "
                f"SELECT CAST(area_id AS INTEGER), anno, variabile, valore, fonte FROM {nome}"
            )
            con.unregister(nome)
        registra_caricamento(con, FONTE, len(dati) + len(com))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"circoscrizioni": len(per_circ), "sezioni": len(per_sez), "comune": len(com)}


def elettorali_da_db(con: duckdb.DuckDBPyConnection) -> gpd.GeoDataFrame:
    righe = con.execute(
        "SELECT codice, ST_AsWKB(geometria) FROM area "
        "WHERE tipo = 'sezione' AND geometria IS NOT NULL"
    ).fetchall()
    if not righe:
        raise ErroreIngest("Sezioni elettorali non caricate: eseguire prima app.ingest.sezioni")
    return gpd.GeoDataFrame(
        {"codice": [r[0] for r in righe]},
        geometry=[wkb.loads(bytes(r[1])) for r in righe],
        crs="EPSG:4326",
    )


def main() -> None:
    sezioni = leggi_sezioni(scarica(URL_DATI, FONTE))
    geometrie = leggi_geometrie(scarica(URL_BASI, FONTE))
    condizione = scarica(
        SDMX.format(flusso="DF_DCSS_ISTR_LAV_PEN_2_TV_3", chiave="........"),
        FONTE,
        nome_file="istat_condizione_professionale_eta_torino.csv",
        intestazioni=ACCETTA_CSV,
    )
    posizione = scarica(
        SDMX.format(flusso="DF_DCSS_EMPLP_1_COM", chiave="....."),
        FONTE,
        nome_file="istat_occupati_posizione_torino.csv",
        intestazioni=ACCETTA_CSV,
    )
    comunali = tavole_comunali(condizione, posizione)

    totale = int(sezioni["cens_pop"].sum())
    if totale != int(geometrie["POP21"].sum()):
        raise ErroreIngest(f"Popolazione dati {totale} diversa da basi territoriali")
    senza_geo = set(sezioni["SEZ21_ID"]) - set(geometrie["SEZ21_ID"])
    if senza_geo:
        raise ErroreIngest(f"{len(senza_geo)} sezioni di censimento senza geometria")

    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        elettorali = elettorali_da_db(con)
        abitate = geometrie[geometrie["SEZ21_ID"].isin(sezioni["SEZ21_ID"])]
        elettorale = assegna_sezioni_elettorali(abitate, elettorali)
        n = scrivi(con, sezioni, elettorale, comunali)

    # Rapporto: concordanza tra circoscrizione ISTAT e circoscrizione della sezione elettorale.
    with db.connetti(impostazioni().db_path, sola_lettura=True) as con:
        circ_el = dict(
            con.execute(
                "SELECT s.codice, c.codice FROM area s JOIN area c ON c.id = s.id_padre "
                "WHERE s.tipo = 'sezione'"
            ).fetchall()
        )
    s = sezioni.assign(sezione=sezioni["SEZ21_ID"].map(elettorale))
    s["circ_geo"] = s["sezione"].map(circ_el)
    concorde = s.loc[s["circ_geo"] == s["circoscrizione"], "cens_pop"].sum() / totale
    DIR_PROCESSED.mkdir(parents=True, exist_ok=True)
    s[["SEZ21_ID", "circoscrizione", "sezione", "circ_geo", "cens_pop"]].to_csv(
        DIR_PROCESSED / "censimento_sezioni_elettorali.csv", index=False
    )
    residenti = f"{totale:,}".replace(",", ".")
    print(f"Sezioni di censimento abitate: {len(sezioni)}, residenti 2021: {residenti}")
    print(f"Righe scritte: {n}")
    print(f"Popolazione con la stessa circoscrizione ISTAT e geometrica: {concorde:.2%}")
    print(f"Tavole comunali: {len(comunali)} valori")


if __name__ == "__main__":
    main()
