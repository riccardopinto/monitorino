"""Configurazioni Chart.js per i report, costruite in Python e serializzate nella pagina.

Ogni funzione restituisce {id, larghezza, altezza, config}. Niente animazioni e dimensioni fisse,
così la stampa è identica a ogni esecuzione. Colori: area in blu, Torino in grigio; barre
divergenti rosso/blu come nella dashboard.
"""

from __future__ import annotations

AREA = "#2a78d6"
CITTA = "#b8c4d4"
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # stesso ordine di temi.js
NEGATIVO = "#d6604d"
POSITIVO = "#4393c3"
NEUTRO = "#bdbdbd"
LARGHEZZA = 680
GRIGLIA = "#e5e5e2"
TESTO = "#1d2330"


def _assi(orizzontale: bool, minimo=None, massimo=None, titolo: str = "") -> dict:
    valori = {"grid": {"color": GRIGLIA}, "ticks": {"color": TESTO, "font": {"size": 10}}}
    if minimo is not None:
        valori["min"] = minimo
    if massimo is not None:
        valori["max"] = massimo
    if titolo:
        valori["title"] = {"display": True, "text": titolo, "font": {"size": 10}}
    categorie = {"grid": {"display": False}, "ticks": {"color": TESTO, "font": {"size": 10}}}
    return {"x": valori, "y": categorie} if orizzontale else {"x": categorie, "y": valori}


def _grafico(id_: str, tipo: str, dati: dict, opzioni: dict, altezza: int) -> dict:
    return {"id": id_, "larghezza": LARGHEZZA, "altezza": altezza,
            "config": {"type": tipo, "data": dati, "options": opzioni}}  # fmt: skip


def barre(
    id_: str,
    etichette: list[str],
    serie: list[dict],
    *,
    titolo_valori: str = "",
    massimo: float | None = None,
    orizzontale: bool = True,
) -> dict:
    """Barre affiancate; ``serie`` = [{nome, valori, colore}]."""
    dati = {
        "labels": etichette,
        "datasets": [
            {"label": s["nome"], "data": s["valori"], "backgroundColor": s["colore"],
             "borderRadius": 3, "barPercentage": 0.85, "categoryPercentage": 0.8}
            for s in serie
        ],
    }  # fmt: skip
    opzioni = {
        "indexAxis": "y" if orizzontale else "x",
        "scales": _assi(orizzontale, 0, massimo, titolo_valori),
        "plugins": {"legend": {"display": len(serie) > 1, "position": "bottom",
                               "labels": {"boxWidth": 10, "font": {"size": 10}}}},
    }  # fmt: skip
    altezza = max(120, len(etichette) * (14 * len(serie) + 10) + 60) if orizzontale else 260
    return _grafico(id_, "bar", dati, opzioni, altezza)


def divergenti(id_: str, etichette: list[str], valori: list[float], titolo: str = "") -> dict:
    """Barre del saldo netto (−100…+100), rosse se negative e blu se positive."""
    colori = [POSITIVO if v > 0 else NEGATIVO if v < 0 else NEUTRO for v in valori]
    dati = {"labels": etichette, "datasets": [
        {"label": titolo or "Saldo netto (punti)", "data": valori, "backgroundColor": colori,
         "borderRadius": 3, "barThickness": 12}]}  # fmt: skip
    opzioni = {
        "indexAxis": "y",
        "scales": _assi(True, -100, 100, titolo or "saldo netto (punti)"),
        "plugins": {"legend": {"display": False}},
    }
    return _grafico(id_, "bar", dati, opzioni, max(110, len(etichette) * 22 + 60))


def linee(id_: str, etichette: list[str], serie: list[dict], titolo_valori: str = "") -> dict:
    dati = {
        "labels": etichette,
        "datasets": [
            {"label": s["nome"], "data": s["valori"], "borderColor": s["colore"],
             "backgroundColor": s["colore"], "borderWidth": 2, "pointRadius": 2, "tension": 0.2}
            for s in serie
        ],
    }  # fmt: skip
    opzioni = {
        "scales": _assi(False, 0, None, titolo_valori),
        "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 10,
                                                                "font": {"size": 10}}}},
    }  # fmt: skip
    return _grafico(id_, "line", dati, opzioni, 240)


def piramide(id_: str, p: dict) -> dict:
    """Piramide d'età: maschi a sinistra (valori negativi), femmine a destra; Torino a righe."""
    dati = {
        "labels": p["classi"],
        "datasets": [
            {"label": "Maschi", "data": [-(v or 0) for v in p["maschi"]],
             "backgroundColor": SERIE[0], "stack": "area", "barPercentage": 1.0,
             "categoryPercentage": 0.9},
            {"label": "Femmine", "data": p["femmine"], "backgroundColor": SERIE[1],
             "stack": "area", "barPercentage": 1.0, "categoryPercentage": 0.9},
            {"label": "Torino", "data": [-(v or 0) for v in p["citta_maschi"]],
             "backgroundColor": "rgba(0,0,0,0)", "borderColor": TESTO, "borderWidth": 1,
             "stack": "citta", "barPercentage": 1.0, "categoryPercentage": 0.9},
            {"label": "Torino ", "data": p["citta_femmine"], "backgroundColor": "rgba(0,0,0,0)",
             "borderColor": TESTO, "borderWidth": 1, "stack": "citta", "barPercentage": 1.0,
             "categoryPercentage": 0.9},
        ],
    }  # fmt: skip
    opzioni = {
        "indexAxis": "y",
        "scales": {
            "x": {"stacked": False, "grid": {"color": GRIGLIA},
                  "title": {"display": True, "text": "% dei residenti (maschi a sinistra)",
                            "font": {"size": 10}}},
            "y": {"stacked": True, "reverse": True, "grid": {"display": False},
                  "ticks": {"font": {"size": 9}}},
        },
        "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 10,
                    "font": {"size": 10}, "filter": "senzaDoppioni"}}},
    }  # fmt: skip
    return _grafico(id_, "bar", dati, opzioni, 360)
