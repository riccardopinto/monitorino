"""Sezioni elettorali: corrispondenza con le circoscrizioni e confini approssimati.

Il Comune non pubblica i confini delle sezioni. Li stimiamo così:
1. abbiniamo il file civico -> sezione (2017) ai civici georeferenziati (2019) per via e numero;
2. dentro ogni circoscrizione costruiamo le celle di Voronoi dei civici abbinati;
3. ritagliamo le celle sul confine della circoscrizione e le uniamo per sezione.
Le aree risultanti hanno ``approssimata = true``. Metodo e limiti in docs/fonti_dati.md.

Uso: ``uv run python -m app.ingest.sezioni`` (dopo ``app.ingest.circoscrizioni``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import shapely
from shapely import wkb

from app.core import db
from app.core.codici import normalizza_circoscrizione, normalizza_sezione
from app.core.config import impostazioni
from app.ingest._comune import DIR_PROCESSED, registra_caricamento, scarica

FONTE_SEGGI = "comune_seggi"
URL_SEGGI = "https://risorse.comune.torino.it/opendata/elezioni/toseggio.csv"
FONTE_CIVICI = "comune_civici"
URL_CIVICI = (
    "https://risorse.comune.torino.it/opendata/geodata/civici_WGS84_EPSG4326_csv_201910.csv"
)
ANNO_SEGGI = 2017  # data di rilascio del file civico -> sezione
SOGLIA_ABBINAMENTO = 0.90
CRS_METRICO = "EPSG:32632"


class ErroreIngest(RuntimeError):
    pass


# --- normalizzazione --------------------------------------------------------


def chiave_via(nome: str) -> str:
    """Chiave di confronto per i nomi di via, indipendente dall'ordine delle parole.

    'VIA BARBAROUX GIUSEPPE' e 'Via Giuseppe Barbaroux' danno la stessa chiave.
    """
    testo = unicodedata.normalize("NFKD", str(nome))
    testo = "".join(c for c in testo if not unicodedata.combining(c)).upper()
    parole = re.sub(r"[^A-Z0-9]+", " ", testo).split()
    return " ".join(sorted(parole))


def numero_base(civico: object) -> int | None:
    """Parte numerica iniziale del civico: '28/A' -> 28, '63 scala B' -> 63."""
    trovato = re.match(r"\s*(\d+)", str(civico))
    if not trovato:
        return None
    numero = int(trovato.group(1))
    return numero or None


def _decimale(valore: object) -> float:
    return float(str(valore).replace(",", "."))


# --- lettura ----------------------------------------------------------------


def leggi_seggi(percorso: Path) -> pd.DataFrame:
    """Righe civico -> sezione. Esclude gli pseudo-indirizzi con circoscrizione 0."""
    df = pd.read_csv(percorso, dtype=str, encoding="utf-8")
    df = df[df["CIRCOSCRIZIONE"].str.strip() != "0"]
    out = pd.DataFrame(
        {
            "via": df["DESCRIZIONE_VIA"].map(chiave_via),
            "numero": df["NUMERO_CIVICO"].map(numero_base),
            "sezione": df["SEZIONE"].map(normalizza_sezione),
            "circoscrizione": df["CIRCOSCRIZIONE"].map(normalizza_circoscrizione),
        }
    )
    return out.dropna(subset=["numero"]).astype({"numero": int})


def leggi_civici(percorso: Path) -> pd.DataFrame:
    df = pd.read_csv(percorso, dtype=str, encoding="utf-8")
    out = pd.DataFrame(
        {
            "via": df["VIA"].map(chiave_via),
            "numero": df["CIVICO"].map(numero_base),
            "lon": df["COORDINATA_X"].map(_decimale),
            "lat": df["COORDINATA_Y"].map(_decimale),
        }
    )
    return out.dropna().astype({"numero": int})


# --- abbinamento ------------------------------------------------------------


def _moda(serie: pd.Series) -> str:
    # In caso di parità vince il codice più basso, per avere risultati ripetibili.
    conteggi = serie.value_counts()
    massimi = conteggi[conteggi == conteggi.max()].index
    return min(massimi, key=lambda v: (len(v), v))


def circoscrizione_per_sezione(seggi: pd.DataFrame) -> pd.Series:
    """Circoscrizione di ogni sezione: quella della maggioranza dei suoi civici."""
    return seggi.groupby("sezione")["circoscrizione"].agg(_moda)


@dataclass
class Abbinamento:
    punti: pd.DataFrame  # sezione, circoscrizione, lon, lat
    chiavi_totali: int
    chiavi_abbinate: int

    @property
    def quota(self) -> float:
        return self.chiavi_abbinate / self.chiavi_totali if self.chiavi_totali else 0.0


def abbina(seggi: pd.DataFrame, civici: pd.DataFrame) -> Abbinamento:
    circ = circoscrizione_per_sezione(seggi)
    # Una chiave (via, numero) può comparire con più sezioni (scale diverse): vince la maggioranza.
    chiavi = seggi.groupby(["via", "numero"])["sezione"].agg(_moda).reset_index()
    uniti = chiavi.merge(civici, on=["via", "numero"], how="inner")
    # Punti con le stesse coordinate e sezioni diverse: una sola sezione per punto.
    punti = uniti.groupby(["lon", "lat"])["sezione"].agg(_moda).reset_index()
    punti["circoscrizione"] = punti["sezione"].map(circ)
    abbinate = uniti[["via", "numero"]].drop_duplicates()
    return Abbinamento(
        punti=punti[["sezione", "circoscrizione", "lon", "lat"]],
        chiavi_totali=len(chiavi),
        chiavi_abbinate=len(abbinate),
    )


# --- geometrie --------------------------------------------------------------


def poligoni_sezioni(punti: pd.DataFrame, circoscrizioni: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Celle di Voronoi dei punti, ritagliate per circoscrizione e unite per sezione.

    ``circoscrizioni`` ha colonne codice e geometry in EPSG:4326. Restituisce
    sezione, circoscrizione, n_punti, n_fuori_circ e geometry in EPSG:4326.
    """
    circ_m = circoscrizioni.to_crs(CRS_METRICO).set_index("codice").geometry
    pts = gpd.GeoDataFrame(
        punti, geometry=gpd.points_from_xy(punti["lon"], punti["lat"]), crs="EPSG:4326"
    ).to_crs(CRS_METRICO)

    parti = []
    for codice, confine in circ_m.items():
        sel = pts[pts["circoscrizione"] == codice]
        if sel.empty:
            continue
        fuori = ~sel.geometry.within(confine)
        if len(sel) == 1:
            celle = [confine]
        else:
            diagramma = shapely.voronoi_polygons(
                shapely.MultiPoint(list(sel.geometry)), extend_to=confine, ordered=True
            )
            celle = list(shapely.get_parts(diagramma))
        parti.append(
            gpd.GeoDataFrame(
                {
                    "sezione": sel["sezione"].to_numpy(),
                    "circoscrizione": codice,
                    "fuori": fuori.to_numpy(),
                },
                geometry=shapely.intersection(celle, confine),
                crs=CRS_METRICO,
            )
        )

    celle = pd.concat(parti, ignore_index=True)
    celle["n_punti"] = 1
    unite = celle.dissolve(
        by=["sezione", "circoscrizione"], aggfunc={"n_punti": "sum", "fuori": "sum"}
    ).reset_index()
    unite = unite.rename(columns={"fuori": "n_fuori_circ"})
    unite = unite[~unite.geometry.is_empty]
    return unite.to_crs("EPSG:4326")


# --- scrittura --------------------------------------------------------------


def leggi_circoscrizioni(con: duckdb.DuckDBPyConnection) -> gpd.GeoDataFrame:
    righe = con.execute(
        "SELECT codice, ST_AsWKB(geometria) FROM area WHERE tipo = 'circoscrizione'"
    ).fetchall()
    if len(righe) != 8:
        raise ErroreIngest(
            "Circoscrizioni non caricate: eseguire prima "
            "`uv run python -m app.ingest.circoscrizioni`"
        )
    return gpd.GeoDataFrame(
        {"codice": [r[0] for r in righe]},
        geometry=[wkb.loads(bytes(r[1])) for r in righe],
        crs="EPSG:4326",
    )


def scrivi(
    con: duckdb.DuckDBPyConnection,
    poligoni: gpd.GeoDataFrame,
    circ_per_sezione: pd.Series,
    *,
    anno: int = ANNO_SEGGI,
) -> None:
    """Sostituisce le sezioni in area e la loro corrispondenza per ``anno``. Idempotente."""
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM area WHERE tipo = 'sezione'")
        con.execute("DELETE FROM sezione_area WHERE anno = ?", [anno])
        padri = dict(
            con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall()
        )
        con.executemany(
            "INSERT INTO area (tipo, codice, nome, geometria, id_padre, approssimata) "
            "VALUES ('sezione', ?, ?, ST_GeomFromWKB(?), ?, true)",
            [
                (r.sezione, f"Sezione {r.sezione}", r.geometry.wkb, padri[r.circoscrizione])
                for r in poligoni.itertuples()
            ],
        )
        con.executemany(
            "INSERT INTO sezione_area (sezione, anno, circoscrizione) VALUES (?, ?, ?)",
            [(sez, anno, circ) for sez, circ in circ_per_sezione.items()],
        )
        registra_caricamento(con, FONTE_SEGGI, len(circ_per_sezione))
        registra_caricamento(con, FONTE_CIVICI, int(poligoni["n_punti"].sum()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def rapporto(
    seggi: pd.DataFrame, poligoni: gpd.GeoDataFrame, circ_per_sezione: pd.Series
) -> pd.DataFrame:
    civici_seggi = seggi.drop_duplicates(["via", "numero", "sezione"]).groupby("sezione").size()
    geo = poligoni.set_index("sezione")
    out = pd.DataFrame({"circoscrizione": circ_per_sezione})
    out["civici_nel_file_seggi"] = civici_seggi.reindex(out.index).fillna(0).astype(int)
    out["punti_abbinati"] = geo["n_punti"].reindex(out.index).fillna(0).astype(int)
    out["punti_fuori_circoscrizione"] = geo["n_fuori_circ"].reindex(out.index).fillna(0)
    out["ha_geometria"] = out.index.isin(geo.index)
    out.index.name = "sezione"
    return out.sort_index(key=lambda s: s.astype(int))


def main() -> None:
    seggi = leggi_seggi(scarica(URL_SEGGI, FONTE_SEGGI))
    civici = leggi_civici(scarica(URL_CIVICI, FONTE_CIVICI))
    abbinamento = abbina(seggi, civici)
    print(
        f"Civici del file seggi abbinati: {abbinamento.chiavi_abbinate} su "
        f"{abbinamento.chiavi_totali} ({abbinamento.quota:.1%})"
    )
    if abbinamento.quota < SOGLIA_ABBINAMENTO:
        raise ErroreIngest(
            f"Abbinamento sotto la soglia del {SOGLIA_ABBINAMENTO:.0%}: "
            "verificare la normalizzazione delle vie prima di proseguire"
        )

    circ_per_sezione = circoscrizione_per_sezione(seggi)
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        poligoni = poligoni_sezioni(abbinamento.punti, leggi_circoscrizioni(con))
        scrivi(con, poligoni, circ_per_sezione)

    rap = rapporto(seggi, poligoni, circ_per_sezione)
    DIR_PROCESSED.mkdir(parents=True, exist_ok=True)
    percorso = DIR_PROCESSED / "sezioni_rapporto.csv"
    rap.to_csv(percorso)
    senza = rap[~rap["ha_geometria"]]
    print(f"Sezioni: {len(rap)}, con confini approssimati: {int(rap['ha_geometria'].sum())}")
    if not senza.empty:
        print(f"Sezioni senza punti abbinati (nessun confine): {', '.join(senza.index)}")
    fuori = int(rap["punti_fuori_circoscrizione"].sum())
    print(f"Punti fuori dalla circoscrizione dichiarata: {fuori}")
    print(f"Rapporto completo: {percorso}")


if __name__ == "__main__":
    main()
