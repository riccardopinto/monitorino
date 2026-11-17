"""API del modulo temi. Per i social solo numeri aggregati: mai contenuti singoli."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated

import duckdb
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.api.dipendenze import cursore
from app.llm import prompt_temi as pt
from app.temi import aggrega, chat

router = APIRouter(prefix="/api/temi", tags=["temi"])
Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]
TIPI_NEWS = ("news", "istituzionale")


def _dal(settimane: int) -> date:
    oggi = date.today()
    return oggi - timedelta(days=oggi.weekday()) - timedelta(weeks=max(1, settimane) - 1)


def _area(con, codice: str | None) -> int | None:
    if not codice:
        return None
    riga = con.execute(
        "SELECT id FROM area WHERE tipo = 'circoscrizione' AND codice = ?", [codice]
    ).fetchone()
    if not riga:
        raise HTTPException(404, f"Circoscrizione {codice!r} non trovata")
    return riga[0]


@router.get("/stato")
def stato(con: Con) -> dict:
    tot, da_classificare, ultima = con.execute(
        "SELECT count(*), count(*) FILTER (classificato_da IS NULL), max(raccolto_il) "
        "FROM documento"
    ).fetchone()
    per_tipo = dict(
        con.execute(
            "SELECT coalesce(tipo_fonte, '?'), count(*) FROM documento GROUP BY 1"
        ).fetchall()
    )
    (ultima_settimana,) = con.execute("SELECT max(settimana) FROM tema_aggregato").fetchone()
    return {
        "documenti": tot,
        "per_tipo": per_tipo,
        "da_classificare": da_classificare,
        "ultima_raccolta": ultima.isoformat(timespec="minutes") if ultima else None,
        "ultima_settimana": ultima_settimana.isoformat() if ultima_settimana else None,
    }


@router.get("/matrice")
def matrice(con: Con, settimane: Annotated[int, Query(ge=1, le=52)] = 4) -> dict:
    """Temi × circoscrizioni: volume e sentiment medio (pesato sul volume) nel periodo."""
    dal = _dal(settimane)
    righe = con.execute(
        """
        SELECT t.tema, a.codice, sum(t.volume) AS volume,
               sum(t.sentiment_medio * t.volume) / nullif(sum(t.volume), 0) AS sentiment
        FROM tema_aggregato t LEFT JOIN area a ON a.id = t.area_id
        WHERE t.settimana >= ? GROUP BY ALL
        """,
        [dal],
    ).fetchall()
    citta = {r[0]: {"volume": int(r[2]), "sentiment": _r(r[3])} for r in righe if r[1] is None}
    temi = sorted(citta, key=lambda t: -citta[t]["volume"])
    celle = [
        {"tema": r[0], "area": r[1], "volume": int(r[2]), "sentiment": _r(r[3])}
        for r in righe
        if r[1] is not None
    ]
    return {
        "dal": dal.isoformat(),
        "settimane": settimane,
        "temi": temi,
        "citta": citta,
        "celle": celle,
    }


def _r(v):
    return None if v is None else round(float(v), 2)


@router.get("/andamento")
def andamento(
    con: Con,
    area: str | None = None,
    n: Annotated[int, Query(ge=1, le=10)] = 5,
    settimane: Annotated[int, Query(ge=2, le=52)] = 12,
) -> dict:
    """Serie settimanali dei primi ``n`` temi dell'area (o della città)."""
    area_id = _area(con, area)
    dal = _dal(settimane)
    filtro = "t.area_id = ?" if area_id is not None else "t.area_id IS NULL"
    parametri = [dal, area_id] if area_id is not None else [dal]
    righe = con.execute(
        f"SELECT tema, settimana, volume FROM tema_aggregato t WHERE settimana >= ? AND {filtro}",
        parametri,
    ).fetchall()
    totali: dict[str, int] = {}
    for tema, _, v in righe:
        totali[tema] = totali.get(tema, 0) + v
    primi = sorted(totali, key=lambda t: -totali[t])[:n]
    settimane_l = [(dal + timedelta(weeks=i)).isoformat() for i in range(settimane)]
    serie = {t: [0] * settimane for t in primi}
    for tema, sett, v in righe:
        if tema in serie:
            i = (sett - dal).days // 7
            if 0 <= i < settimane:
                serie[tema][i] = v
    return {"settimane": settimane_l, "serie": [{"tema": t, "volumi": serie[t]} for t in primi]}


@router.get("/articoli")
def articoli(
    con: Con,
    tema: str | None = None,
    area: str | None = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict]:
    """Ultimi articoli di news e comunicati (mai contenuti social)."""
    area_id = _area(con, area)
    condizioni = ["tipo_fonte IN ('news', 'istituzionale')", "coalesce(pertinente, true)"]
    parametri: list = []
    if tema:
        condizioni.append("tema = ?")
        parametri.append(tema)
    if area_id is not None:
        condizioni.append("area_id = ?")
        parametri.append(area_id)
    righe = con.execute(
        "SELECT titolo, fonte, data, url, tema FROM documento WHERE "
        + " AND ".join(condizioni)
        + " ORDER BY data DESC, id DESC LIMIT ?",
        [*parametri, limite],
    ).fetchall()
    return [
        {"titolo": t, "testata": f, "data": d.isoformat() if d else None, "url": u, "tema": te}
        for t, f, d, u, te in righe
    ]


@router.get("/social")
def social(con: Con, settimane: Annotated[int, Query(ge=1, le=52)] = 4) -> dict:
    """Social: solo conteggi per tema e circoscrizione, nessun contenuto."""
    righe = con.execute(
        "SELECT d.tema, a.codice, count(*) FROM documento d LEFT JOIN area a ON a.id = d.area_id "
        "WHERE d.tipo_fonte = 'social' AND d.tema IS NOT NULL AND coalesce(d.pertinente, true) "
        "AND d.data >= ? GROUP BY ALL",
        [_dal(settimane)],
    ).fetchall()
    return {"conteggi": [{"tema": t, "area": a, "n": n} for t, a, n in righe]}


@router.get("/prompt", response_class=PlainTextResponse)
def scarica_prompt(con: Con, limite: Annotated[int, Query(ge=1, le=300)] = chat.PER_FILE):
    """Prompt per classificare in una chat i primi ``limite`` documenti non classificati."""
    documenti = pt.documenti_da_classificare(con, limite=limite)
    if not documenti:
        raise HTTPException(404, "Nessun documento da classificare")
    nome = f"temi_prompt_{date.today():%Y%m%d}.md"
    return PlainTextResponse(
        chat.prompt(documenti),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.post("/classificazioni")
def importa(con: Con, testo: Annotated[str, Body(media_type="text/plain")]) -> dict:
    """Importa il JSON prodotto dalla chat e ricalcola l'aggregazione."""
    try:
        esito = chat.importa(con, testo)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"JSON non valido: {e}") from e
    righe = aggrega.aggrega(con)
    return {
        "applicati": len(esito["applicati"]),
        "errori": esito["errori"][:20],
        "sconosciuti": esito["sconosciuti"],
        "gia_classificati": len(esito["gia_classificati"]),
        "righe_aggregate": righe,
    }
