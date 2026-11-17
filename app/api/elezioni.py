"""API del modulo storico elettorale."""

from __future__ import annotations

import math
from typing import Annotated, Literal

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.analysis import elezioni as an
from app.api.dipendenze import cursore

router = APIRouter(prefix="/api", tags=["elezioni"])

Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]
LivelloMappa = Literal["circoscrizione", "sezione"]
Metrica = Literal["quota", "voti", "affluenza", "variazione"]


def _num(v: float | None, cifre: int = 2) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), cifre)


def _esiste(con: duckdb.DuckDBPyConnection, eid: int) -> None:
    if not con.execute("SELECT count(*) FROM elezione WHERE id = ?", [eid]).fetchone()[0]:
        raise HTTPException(404, f"Elezione {eid} non trovata")


@router.get("/elezioni")
def elenco(request: Request, con: Con) -> list[dict]:
    """Elezioni caricate, con i soggetti disponibili per tipo (ordinati per voti in città)."""
    # I risultati cambiano solo con un ingest, che richiede di fermare l'app.
    cache: dict = request.app.state.cache_elezioni
    if "elenco" not in cache:
        out = []
        for eid, nome, tipo, data, turno in con.execute(
            "SELECT id, nome, tipo, data, turno FROM elezione ORDER BY data, tipo, turno"
        ).fetchall():
            liste = an.ha_liste(con, eid)
            soggetti = {}
            for t in ("lista", "forza", "area", "candidato"):
                if t == "lista" and not liste:
                    continue
                r = an.risultati(con, eid, "citta", t)
                nomi = [s for s in r["soggetto"].tolist() if s is not None]
                if nomi:
                    soggetti[t] = nomi
            out.append(
                {
                    "id": eid,
                    "nome": nome,
                    "tipo": tipo,
                    "data": data.isoformat(),
                    "turno": turno,
                    "ha_liste": liste,
                    "soggetti": soggetti,
                }
            )
        cache["elenco"] = out
    return cache["elenco"]


@router.get("/elezioni/{eid}/mappa")
def mappa(
    eid: int,
    con: Con,
    livello: LivelloMappa = "circoscrizione",
    metrica: Metrica = "quota",
    tipo: an.Tipo = "area",
    soggetto: str | None = None,
    confronto: Annotated[int | None, Query(description="Elezione di partenza")] = None,
) -> dict:
    """Valori per area da colorare in mappa, più il valore cittadino di riferimento.

    variazione = quota nell'elezione ``eid`` meno quota nell'elezione ``confronto``, in punti.
    """
    _esiste(con, eid)
    if metrica == "affluenza":
        dati = an.affluenza(con, eid, livello)
        citta = an.affluenza(con, eid, "citta")["affluenza"].iloc[0]
        valori = [
            {"codice": r.area, "valore": _num(r.affluenza * 100), "voti": int(r.votanti)}
            for r in dati.itertuples()
            if r.area is not None
        ]
        return {"metrica": metrica, "unita": "%", "valori": valori, "citta": _num(citta * 100)}

    if not soggetto:
        raise HTTPException(422, "Indicare il soggetto (lista, forza, area o candidato)")

    if metrica == "variazione":
        if confronto is None:
            raise HTTPException(422, "La variazione richiede un'elezione di confronto")
        _esiste(con, confronto)
        dati = an.variazione(con, confronto, eid, livello, tipo)
        dati = dati[dati.soggetto == soggetto]
        citta = an.variazione(con, confronto, eid, "citta", tipo)
        citta = citta[citta.soggetto == soggetto]["variazione_punti"]
        valori = [
            {"codice": r.area, "valore": _num(r.variazione_punti)}
            for r in dati.itertuples()
            if r.area is not None
        ]
        return {
            "metrica": metrica,
            "unita": "punti",
            "valori": valori,
            "citta": _num(citta.iloc[0]) if len(citta) else None,
        }

    dati = an.risultati(con, eid, livello, tipo)
    dati = dati[dati.soggetto == soggetto]
    citta = an.risultati(con, eid, "citta", tipo)
    citta = citta[citta.soggetto == soggetto]
    if citta.empty:
        raise HTTPException(404, f"{soggetto!r} non presente in questa elezione")
    if metrica == "voti":
        valori = [{"codice": r.area, "valore": int(r.voti)} for r in dati.itertuples()]
        return {"metrica": metrica, "unita": "voti", "valori": valori, "citta": None}
    valori = [
        {"codice": r.area, "valore": _num(r.quota * 100), "voti": int(r.voti)}
        for r in dati.itertuples()
        if r.area is not None
    ]
    return {
        "metrica": metrica,
        "unita": "%",
        "valori": valori,
        "citta": _num(citta["quota"].iloc[0] * 100),
    }


@router.get("/elezioni/{eid}/area")
def dettaglio_area(
    eid: int,
    con: Con,
    livello: an.Livello,
    codice: str = "Torino",
    tipo: an.Tipo = "area",
) -> dict:
    """Risultati dell'area selezionata e media cittadina, per il pannello dettagli.

    Con livello "citta" (codice "Torino") restituisce i risultati di tutta la città.
    """
    _esiste(con, eid)
    area = an.risultati(con, eid, livello, tipo)
    area = area[area.area == codice]
    if area.empty:
        raise HTTPException(404, f"Nessun dato per {livello} {codice} in questa elezione")
    citta = an.risultati(con, eid, "citta", tipo).set_index("soggetto")
    aff_area = an.affluenza(con, eid, livello).set_index("area")
    aff_citta = an.affluenza(con, eid, "citta").iloc[0]
    return {
        "tipo": tipo,
        "righe": [
            {
                "soggetto": r.soggetto,
                "voti": int(r.voti),
                "quota": _num(r.quota * 100),
                "quota_citta": _num(citta["quota"].get(r.soggetto, float("nan")) * 100),
            }
            for r in area.itertuples()
        ],
        "affluenza": _num(aff_area.loc[codice, "affluenza"] * 100)
        if codice in aff_area.index
        else None,
        "affluenza_citta": _num(aff_citta["affluenza"] * 100),
    }


@router.get("/flussi")
def flussi(
    con: Con,
    da: int,
    a: int,
    circoscrizione: str | None = None,
) -> dict:
    """Flussi stimati tra aree politiche di due elezioni (regressione ecologica)."""
    _esiste(con, da)
    _esiste(con, a)
    try:
        f = an.flussi(con, da, a, circoscrizione)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "etichetta": f.etichetta,
        "da": f.categorie_da,
        "a": f.categorie_a,
        "quote": [[_num(v * 100, 1) for v in riga] for riga in f.matrice.to_numpy()],
        "elettori": f.elettori.to_numpy().tolist(),
        "r2": {k: _num(v) for k, v in f.r2.items()},
        "n_sezioni": f.n_sezioni,
    }
