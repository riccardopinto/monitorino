"""API del modulo demografia."""

from __future__ import annotations

import math
from typing import Annotated, Literal

import duckdb
import numpy as np
from fastapi import APIRouter, Depends, HTTPException

from app.analysis import demografia as dm
from app.analysis import elezioni as an
from app.api.dipendenze import cursore

router = APIRouter(prefix="/api/demografia", tags=["demografia"])

Con = Annotated[duckdb.DuckDBPyConnection, Depends(cursore)]
LivelloArea = Literal["circoscrizione", "sezione"]
NOTA_SOGLIA = (
    f"Per le sezioni con meno di {dm.SOGLIA_RESIDENTI_SEZIONE} residenti gli indicatori non "
    "si mostrano: con numeri così piccoli non sono affidabili."
)


def _num(v, cifre: int = 2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), cifre)


def _indicatore(chiave: str) -> dm.Indicatore:
    if chiave not in dm.INDICATORI:
        raise HTTPException(404, f"Indicatore {chiave!r} sconosciuto")
    return dm.INDICATORI[chiave]


def _citta(con, chiave: str, come: str = "citta") -> float | None:
    """Valore cittadino (None se la fonte non è caricata)."""
    v = dm.valori(con, chiave, "citta", come=come)["valore"]
    return _num(v.iloc[0]) if len(v) else None


def _valori(con, chiave: str, livello: str):
    """Valori per area; per le sezioni nasconde quelle sotto la soglia di residenti."""
    v = dm.valori(con, chiave, livello).set_index("area")["valore"]
    if livello == "sezione":
        pop = dm.popolazione_sezioni(con).reindex(v.index)
        v = v.where(pop >= dm.SOGLIA_RESIDENTI_SEZIONE)
    return v


@router.get("/indicatori")
def indicatori() -> list[dict]:
    return [
        {
            "chiave": i.chiave,
            "nome": i.nome,
            "unita": i.unita,
            "nota": i.nota,
            "livelli": {
                lv: {"fonte": f.fonte, "anno": f.anno, "stima": f.stima}
                for lv, f in i.formule.items()
            },
        }
        for i in dm.INDICATORI.values()
    ]


@router.get("/mappa")
def mappa(con: Con, indicatore: str, livello: LivelloArea = "circoscrizione") -> dict:
    ind = _indicatore(indicatore)
    try:
        v = _valori(con, indicatore, livello)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    citta = _citta(con, indicatore)
    f = ind.formule[livello]
    return {
        "indicatore": ind.chiave,
        "nome": ind.nome,
        "unita": ind.unita,
        "fonte": f.fonte,
        "anno": f.anno,
        "stima": f.stima,
        "nota": NOTA_SOGLIA if livello == "sezione" else None,
        "valori": [{"codice": k, "valore": _num(x)} for k, x in v.items() if k is not None],
        "citta": citta,
    }


@router.get("/area")
def scheda(con: Con, livello: LivelloArea, codice: str) -> dict:
    """Scheda dell'area: indicatori a confronto con la città e piramide d'età."""
    righe = []
    for ind in dm.INDICATORI.values():
        if livello not in ind.formule:
            continue
        v = _valori(con, ind.chiave, livello)
        f = ind.formule[livello]
        righe.append(
            {
                "chiave": ind.chiave,
                "nome": ind.nome,
                "unita": ind.unita,
                "valore": _num(v.get(codice)),
                # Il valore cittadino usa la stessa fonte e lo stesso anno dell'area.
                "citta": _citta(con, ind.chiave, come=livello),
                "fonte": f"{f.fonte} ({f.anno})",
                "stima": f.stima,
            }
        )
    if all(r["valore"] is None for r in righe):
        raise HTTPException(404, f"Nessun dato demografico per {livello} {codice}")

    piramide, fonte, anno = dm.piramide(con, livello, codice)
    citta = dm.piramide_istat(con) if livello == "sezione" else dm.piramide(con, "citta")[0]
    piramide = piramide.set_index("classe")
    citta = citta.set_index("classe").reindex(piramide.index).fillna(0)
    tot_area = piramide[["maschi", "femmine"]].to_numpy().sum()
    tot_citta = citta[["maschi", "femmine"]].to_numpy().sum()
    nascondi = livello == "sezione" and tot_area < dm.SOGLIA_RESIDENTI_SEZIONE
    return {
        "indicatori": righe,
        "nota": NOTA_SOGLIA if livello == "sezione" else None,
        "piramide": None
        if nascondi
        else {
            "classi": piramide.index.tolist(),
            # quote % sul totale, così area e città sono confrontabili
            "maschi": [_num(x / tot_area * 100) for x in piramide["maschi"]],
            "femmine": [_num(x / tot_area * 100) for x in piramide["femmine"]],
            "citta_maschi": [_num(x / tot_citta * 100) for x in citta["maschi"]],
            "citta_femmine": [_num(x / tot_citta * 100) for x in citta["femmine"]],
            "fonte": f"{fonte}, {anno}",
        },
    }


@router.get("/dispersione")
def dispersione(
    con: Con,
    indicatore: str,
    elezione: int,
    soggetto: str,
    tipo: an.Tipo = "area",
    livello: LivelloArea = "circoscrizione",
) -> dict:
    """Coppie (indicatore, quota del soggetto) per area, con il coefficiente di correlazione."""
    ind = _indicatore(indicatore)
    if not con.execute("SELECT count(*) FROM elezione WHERE id = ?", [elezione]).fetchone()[0]:
        raise HTTPException(404, f"Elezione {elezione} non trovata")
    x = _valori(con, indicatore, livello)
    r = an.risultati(con, elezione, livello, tipo)
    y = r[r.soggetto == soggetto].set_index("area")["quota"] * 100
    if y.empty:
        raise HTTPException(404, f"{soggetto!r} non presente in questa elezione")
    comuni = x.dropna().index.intersection(y.dropna().index)
    punti = [{"codice": k, "x": _num(x[k]), "y": _num(y[k])} for k in comuni]
    corr = None
    if len(comuni) >= 3:
        corr = _num(float(np.corrcoef(x[comuni].astype(float), y[comuni].astype(float))[0, 1]))
    return {
        "indicatore": {"nome": ind.nome, "unita": ind.unita, "fonte": ind.formule[livello].fonte},
        "soggetto": soggetto,
        "punti": punti,
        "correlazione": corr,
        "n": len(punti),
        "nota": dm.ETICHETTA_ECOLOGICA,
    }
