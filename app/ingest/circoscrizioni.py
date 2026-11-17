"""Ingest dei confini delle 8 circoscrizioni dal geoportale del Comune di Torino.

Uso: ``uv run python -m app.ingest.circoscrizioni``
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import geopandas as gpd

from app.core import db
from app.core.codici import normalizza_circoscrizione
from app.core.config import CIRCOSCRIZIONI, impostazioni, segmenti
from app.ingest._comune import registra_caricamento, scarica

FONTE = "comune_circoscrizioni"
URL = "http://geoportale.comune.torino.it/geodati/zip/circoscrizioni_geo.zip"
CRS_ATTESO = "EPSG:3003"  # Monte Mario / Italy zone 1, come da .prj del Comune


class ErroreIngest(RuntimeError):
    pass


def leggi(percorso: Path) -> gpd.GeoDataFrame:
    """Legge lo shapefile, valida e restituisce codice, nome e geometria in WGS84."""
    gdf = gpd.read_file(percorso)
    if gdf.crs is None:
        raise ErroreIngest("Lo shapefile non ha sistema di riferimento (.prj mancante)")
    if gdf.crs.to_string() != CRS_ATTESO:
        raise ErroreIngest(f"Sistema di riferimento inatteso: {gdf.crs} (atteso {CRS_ATTESO})")
    mancanti = {"NCIRCO", "DENOM"} - set(gdf.columns)
    if mancanti:
        raise ErroreIngest(f"Colonne mancanti nello shapefile: {sorted(mancanti)}")

    out = gpd.GeoDataFrame(
        {
            "codice": gdf["NCIRCO"].map(normalizza_circoscrizione),
            "nome": gdf["DENOM"].astype(str).str.strip(),
        },
        geometry=gdf.geometry.make_valid(),
        crs=gdf.crs,
    ).to_crs("EPSG:4326")

    codici = sorted(out["codice"], key=int)
    if codici != list(CIRCOSCRIZIONI):
        raise ErroreIngest(f"Attese le circoscrizioni 1-8 una volta sola, trovate {codici}")
    return out.sort_values("codice", key=lambda s: s.astype(int)).reset_index(drop=True)


def scrivi(con: duckdb.DuckDBPyConnection, gdf: gpd.GeoDataFrame) -> int:
    """Sostituisce le circoscrizioni in tabella area. Idempotente."""
    righe = [(r.codice, r.nome, r.geometry.wkb) for r in gdf.itertuples()]
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM area WHERE tipo = 'circoscrizione'")
        con.executemany(
            "INSERT INTO area (tipo, codice, nome, geometria, approssimata) "
            "VALUES ('circoscrizione', ?, ?, ST_GeomFromWKB(?), false)",
            righe,
        )
        registra_caricamento(con, FONTE, len(righe))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(righe)


def _quartieri(nome: str) -> list[str]:
    return [q.strip().lower() for q in re.split(r"[,-]", nome) if q.strip()]


def confronta_nomi(gdf: gpd.GeoDataFrame) -> list[str]:
    """Differenze di quartieri tra i nomi ufficiali e config/segmenti.yaml.

    Virgole e trattini si equivalgono: conta l'elenco dei quartieri.
    """
    attesi = segmenti().circoscrizioni
    return [
        f'{r.codice}: geodati "{r.nome}" / segmenti.yaml "{attesi[r.codice]}"'
        for r in gdf.itertuples()
        if _quartieri(r.nome) != _quartieri(attesi[r.codice])
    ]


def main() -> None:
    percorso = scarica(URL, FONTE)
    gdf = leggi(percorso)
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        n = scrivi(con, gdf)
    print(f"Caricate {n} circoscrizioni da {percorso}")
    for r in gdf.itertuples():
        print(f"  {r.codice}  {r.nome}")
    differenze = confronta_nomi(gdf)
    if differenze:
        print("\nNomi diversi da config/segmenti.yaml (non corretti in automatico):")
        for d in differenze:
            print("  " + d)


if __name__ == "__main__":
    main()
