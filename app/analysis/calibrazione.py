"""Calibrazione del laboratorio messaggi sui sondaggi reali.

Quando esce un sondaggio su un tema simulato, si registra il valore reale accanto a quello
simulato per la stessa metrica. L'indice di affidabilità è lo scarto medio assoluto in punti
percentuali: dice quanto le simulazioni si sono discostate dai sondaggi finora, non quanto
sarà precisa la prossima.
"""

from __future__ import annotations

import json
from datetime import date

import duckdb

METRICHE = {
    "favorevoli_pct": "% favorevoli (gradimento 4-5)",
    "avvicina_pct": "% che si avvicinano al candidato",
    "allontana_pct": "% che si allontanano dal candidato",
    "saldo": "saldo netto (avvicina − allontana)",
}
SOGLIE_GIUDIZIO = ((5.0, "buona"), (10.0, "discreta"), (float("inf"), "bassa"))
MIN_CALIBRAZIONI = 3


class ErroreCalibrazione(ValueError):
    pass


def valore_simulato(
    con: duckdb.DuckDBPyConnection,
    simulazione_id: int,
    metrica: str,
    variante: str = "a",
    area: str | None = None,
) -> float:
    if metrica not in METRICHE:
        raise ErroreCalibrazione(f"Metrica non prevista: {metrica}")
    riga = con.execute(
        "SELECT stato, risultati FROM simulazione WHERE id = ?", [simulazione_id]
    ).fetchone()
    if not riga:
        raise ErroreCalibrazione(f"Simulazione {simulazione_id} non trovata")
    stato, risultati = riga
    if stato != "completata":
        raise ErroreCalibrazione("La simulazione non è completa")
    aggregati = json.loads(risultati)["aggregati"].get(variante)
    if aggregati is None:
        raise ErroreCalibrazione(f"La simulazione non ha la variante {variante.upper()}")
    if area is None:
        blocco = aggregati["totale"]
    else:
        blocco = next((a for a in aggregati["aree"] if a["area"] == area), None)
        if blocco is None:
            raise ErroreCalibrazione(f"La circoscrizione {area} non è nella simulazione")
    return float(blocco[metrica])


def registra(
    con: duckdb.DuckDBPyConnection,
    *,
    simulazione_id: int,
    fonte_sondaggio: str,
    metrica: str,
    valore_reale: float,
    data_sondaggio: date | None = None,
    variante: str = "a",
    area: str | None = None,
) -> dict:
    if not fonte_sondaggio.strip():
        raise ErroreCalibrazione("Indicare la fonte del sondaggio")
    minimo = -100.0 if metrica == "saldo" else 0.0
    if not minimo <= valore_reale <= 100:
        raise ErroreCalibrazione(f"Valore reale fuori scala ({minimo:g}–100)")
    simulato = valore_simulato(con, simulazione_id, metrica, variante, area)
    descrizione = fonte_sondaggio.strip()
    if area:
        descrizione += f" (circoscrizione {area})"
    con.execute(
        "INSERT INTO calibrazione (simulazione_id, fonte_sondaggio, valore_simulato, "
        "valore_reale, metrica, data_sondaggio) VALUES (?, ?, ?, ?, ?, ?)",
        [simulazione_id, descrizione, simulato, valore_reale, metrica, data_sondaggio],
    )
    return {"valore_simulato": simulato, "valore_reale": valore_reale,
            "scarto": round(simulato - valore_reale, 1)}  # fmt: skip


def elenco(con: duckdb.DuckDBPyConnection, simulazione_id: int | None = None) -> list[dict]:
    filtro = "WHERE c.simulazione_id = ?" if simulazione_id is not None else ""
    righe = con.execute(
        "SELECT c.simulazione_id, s.proposta, c.fonte_sondaggio, c.metrica, c.data_sondaggio, "
        "c.valore_simulato, c.valore_reale FROM calibrazione c "
        f"LEFT JOIN simulazione s ON s.id = c.simulazione_id {filtro} "
        "ORDER BY c.data_sondaggio DESC NULLS LAST",
        [simulazione_id] if simulazione_id is not None else [],
    ).fetchall()
    chiavi = ["simulazione_id", "proposta", "fonte_sondaggio", "metrica", "data_sondaggio",
              "valore_simulato", "valore_reale"]  # fmt: skip
    out = []
    for r in righe:
        d = dict(zip(chiavi, r, strict=True))
        d["scarto"] = round(d["valore_simulato"] - d["valore_reale"], 1)
        d["data_sondaggio"] = d["data_sondaggio"].isoformat() if d["data_sondaggio"] else None
        out.append(d)
    return out


def affidabilita(con: duckdb.DuckDBPyConnection) -> dict:
    """Indice di affidabilità: numero di calibrazioni e scarto medio assoluto (punti)."""
    righe = elenco(con)
    if not righe:
        testo = "Affidabilità non stimata: nessun confronto con sondaggi reali."
        return {"n": 0, "scarto_medio": None, "distorsione": None, "giudizio": None,
                "testo": testo}  # fmt: skip
    scarti = [r["scarto"] for r in righe]
    mae = sum(abs(s) for s in scarti) / len(scarti)
    distorsione = sum(scarti) / len(scarti)
    giudizio = next(g for soglia, g in SOGLIE_GIUDIZIO if mae <= soglia)
    testo = (
        f"Scarto medio dai sondaggi reali: {mae:.1f} punti su {len(righe)} "
        f"confront{'o' if len(righe) == 1 else 'i'}"
    )
    if len(righe) < MIN_CALIBRAZIONI:
        testo += " (troppo pochi per un giudizio)"
        giudizio = None
    else:
        testo += f": affidabilità {giudizio}"
    if abs(distorsione) >= 3:
        verso = "sovrastimano" if distorsione > 0 else "sottostimano"
        testo += f". In media le simulazioni {verso} di {abs(distorsione):.1f} punti"
    return {"n": len(righe), "scarto_medio": round(mae, 1), "distorsione": round(distorsione, 1),
            "giudizio": giudizio, "testo": testo + "."}  # fmt: skip
