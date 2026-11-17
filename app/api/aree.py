"""Geometrie delle aree in GeoJSON (WGS84) per la mappa."""

from __future__ import annotations

import json
from typing import Annotated, Literal

import duckdb
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.dipendenze import cursore

router = APIRouter(prefix="/api", tags=["aree"])

TipoArea = Literal["circoscrizione", "sezione"]
# Circa 5 metri a 45° di latitudine: invisibile in mappa, riduce molto il peso del GeoJSON.
TOLLERANZA_GRADI = 0.00005

QUERY = """
SELECT a.id, a.tipo, a.codice, a.nome,
       CASE WHEN a.tipo = 'circoscrizione' THEN a.codice ELSE p.codice END AS circoscrizione,
       coalesce(a.approssimata, false) AS approssimata,
       ST_AsGeoJSON(ST_ReducePrecision(
           ST_SimplifyPreserveTopology(a.geometria, ?), 0.000001)) AS geometria
FROM area a
LEFT JOIN area p ON p.id = a.id_padre
WHERE a.tipo = ? AND a.geometria IS NOT NULL
ORDER BY try_cast(a.codice AS INTEGER), a.codice
"""


def geojson_aree(con: duckdb.DuckDBPyConnection, tipo: str) -> dict:
    righe = con.execute(QUERY, [TOLLERANZA_GRADI, tipo]).fetchall()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": id_,
                "properties": {
                    "id": id_,
                    "tipo": tipo_,
                    "codice": codice,
                    "nome": nome,
                    "circoscrizione": circ,
                    "approssimata": approssimata,
                },
                "geometry": json.loads(geometria),
            }
            for id_, tipo_, codice, nome, circ, approssimata, geometria in righe
        ],
    }


@router.get("/aree")
def aree(
    request: Request,
    con: Annotated[duckdb.DuckDBPyConnection, Depends(cursore)],
    tipo: Annotated[TipoArea, Query()] = "circoscrizione",
) -> JSONResponse:
    # Le geometrie cambiano solo con un ingest, che richiede di fermare l'app (DuckDB
    # ammette un solo processo in scrittura): la cache vale per tutta la vita del processo.
    cache: dict[str, dict] = request.app.state.cache_aree
    if tipo not in cache:
        cache[tipo] = geojson_aree(con, tipo)
    return JSONResponse(cache[tipo], media_type="application/geo+json")
