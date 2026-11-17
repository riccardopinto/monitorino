"""Dati che il laboratorio messaggi usa per costruire panel e contesto delle simulazioni."""

from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import pandas as pd

from app.analysis import demografia as dm
from app.analysis import elezioni as an
from app.core.config import Candidato, elenco_candidati, segmenti
from app.ingest.elezioni.consultazioni import PER_CHIAVE

ELEZIONE_CONTESTO = "comunali_2021"
SETTIMANE_TEMI = 4
INDICATORI_CONTESTO = [
    "indice_vecchiaia", "quota_stranieri", "quota_laureati", "tasso_occupazione",
    "reddito_medio", "dimensione_famiglie",
]  # fmt: skip


def candidato(chiave: str) -> Candidato:
    for k, c in elenco_candidati():
        if k == chiave:
            return c
    raise KeyError(f"Candidato {chiave!r} non trovato in config/candidati.yaml")


def profilo_candidato(c: Candidato) -> str:
    righe = [f"{c.nome}, {c.ruolo or 'candidato'}" + (f", lista {c.lista}" if c.lista else "")]
    if c.tono_di_voce:
        righe.append(f"Tono di voce: {c.tono_di_voce}")
    if c.temi_prioritari:
        righe.append("Temi prioritari: " + ", ".join(c.temi_prioritari))
    if c.posizioni_approvate:
        posizioni = [
            p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)
            for p in c.posizioni_approvate
        ]
        righe.append("Posizioni pubbliche: " + "; ".join(posizioni))
    return "\n".join(righe)


def nomi_circoscrizioni(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(
        con.execute("SELECT codice, nome FROM area WHERE tipo = 'circoscrizione'").fetchall()
    )


def popolazione_per_eta(con: duckdb.DuckDBPyConnection, circ: str) -> tuple[pd.Series, pd.Series]:
    """Residenti maschi e femmine per età singola della circoscrizione (Comune, 2025)."""
    righe = con.execute(
        "SELECT variabile, valore FROM demografia d JOIN area a ON a.id = d.area_id "
        "WHERE a.tipo = 'circoscrizione' AND a.codice = ? AND d.fonte = ? "
        "AND (variabile LIKE 'pop_m_eta_%' OR variabile LIKE 'pop_f_eta_%')",
        [circ, dm.COMUNE],
    ).fetchall()
    m: dict[int, float] = {}
    f: dict[int, float] = {}
    for var, v in righe:
        (m if var.startswith("pop_m") else f)[int(var[-3:])] = v
    return pd.Series(m, dtype=float), pd.Series(f, dtype=float)


def pesi_segmenti(
    con: duckdb.DuckDBPyConnection, circ: str, variante: str, segmenti_run: list[dict]
) -> dict[int, float]:
    """Peso di ogni segmento del run nella circoscrizione, rinormalizzato a somma 1.

    Indice = posizione del segmento in ``segmenti_run``.
    """
    righe = con.execute(
        "SELECT s.definizione, p.peso FROM segmento_peso p JOIN segmento s ON s.id = p.segmento_id "
        "JOIN area a ON a.id = p.area_id WHERE a.codice = ? AND a.tipo = 'circoscrizione' "
        "AND p.variante = ?",
        [circ, variante],
    ).fetchall()
    tabella = {}
    for definizione, peso in righe:
        d = json.loads(definizione)
        tabella[(d["fascia_eta"], d["condizione"], d["area_di_voto"])] = peso
    grezzi = {
        i: tabella.get((s["fascia_eta"], s["condizione"], s["area_di_voto"]), 0.0)
        for i, s in enumerate(segmenti_run)
    }
    totale = sum(grezzi.values())
    if totale <= 0:
        raise ValueError(
            f"Pesi assenti per la circoscrizione {circ} (variante {variante}): "
            "eseguire `uv run python -m app.analysis.demografia --pesi`"
        )
    return {i: v / totale for i, v in grezzi.items()}


def adulti_per_circoscrizione(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Residenti maggiorenni per circoscrizione: peso delle aree nel totale cittadino."""
    righe = con.execute(
        "SELECT a.codice, sum(d.valore) FROM demografia d JOIN area a ON a.id = d.area_id "
        "WHERE a.tipo = 'circoscrizione' AND d.fonte = ? AND d.variabile LIKE 'pop_eta_%' "
        "AND CAST(right(d.variabile, 3) AS INTEGER) >= 18 GROUP BY 1",
        [dm.COMUNE],
    ).fetchall()
    return {codice: float(v) for codice, v in righe}


def _id_elezione(con: duckdb.DuckDBPyConnection, chiave: str) -> int | None:
    c = PER_CHIAVE[chiave]
    riga = con.execute(
        "SELECT id FROM elezione WHERE tipo = ? AND data = ? AND turno = ?",
        [c.tipo, c.data, c.turno],
    ).fetchone()
    return riga[0] if riga else None


def _num(v: float, segno: bool = False) -> str:
    """Numero all'italiana: virgola decimale, spazio per le migliaia."""
    testo = f"{v:+,.1f}" if segno else f"{v:,.1f}"
    return testo.replace(",", " ").replace(".", ",")


def contesto_area(con: duckdb.DuckDBPyConnection, circ: str, nome: str) -> str:
    """Testo di contesto della circoscrizione: demografia, voto 2021, temi recenti."""
    parti = [f"Circoscrizione {circ} di Torino ({nome})."]

    righe = []
    for chiave in INDICATORI_CONTESTO:
        ind = dm.INDICATORI[chiave]
        try:
            v = dm.valori(con, chiave, "circoscrizione").set_index("area")["valore"].get(circ)
            t = dm.valori(con, chiave, "citta")["valore"]
        except ValueError:
            continue
        if v is None or t.empty:
            continue
        unita = "" if ind.unita in ("persone",) else f" {ind.unita}"
        righe.append(f"- {ind.nome}: {_num(v)}{unita} (Torino {_num(t.iloc[0])}{unita})")
    if righe:
        parti.append(
            "Dati demografici (fonti: Comune di Torino 2025, ISTAT 2021, MEF 2024):\n"
            + "\n".join(righe)
        )

    eid = _id_elezione(con, ELEZIONE_CONTESTO)
    if eid:
        r = an.risultati(con, eid, "circoscrizione", "area")
        r = r[r.area == circ].sort_values("voti", ascending=False)
        aff = an.affluenza(con, eid, "circoscrizione").set_index("area")["affluenza"].get(circ)
        quote = ", ".join(f"{s} {_num(q * 100)}%" for s, q in zip(r.soggetto, r.quota, strict=True))
        testo = f"Comunali 2021, voti di lista per area politica: {quote}."
        if aff is not None:
            testo += f" Affluenza {_num(aff * 100)}%."
        parti.append(testo)

    oggi = date.today()
    dal = oggi - timedelta(days=oggi.weekday()) - timedelta(weeks=SETTIMANE_TEMI - 1)
    temi = con.execute(
        "SELECT t.tema, sum(t.volume), "
        "sum(t.sentiment_medio * t.volume) / nullif(sum(t.volume), 0) "
        "FROM tema_aggregato t JOIN area a ON a.id = t.area_id "
        "WHERE a.codice = ? AND a.tipo = 'circoscrizione' AND t.settimana >= ? "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
        [circ, dal],
    ).fetchall()
    if temi:
        elenco = "; ".join(
            f"{t} ({n} {'notizia' if n == 1 else 'notizie'}, sentiment {_num(s, segno=True)})"
            for t, n, s in temi
        )
        parti.append(f"Temi più discussi nelle ultime {SETTIMANE_TEMI} settimane: {elenco}.")
    else:
        parti.append(
            f"Temi recenti: nessun dato classificato per questa circoscrizione nelle ultime "
            f"{SETTIMANE_TEMI} settimane."
        )
    return "\n\n".join(parti)


def segmenti_predefiniti() -> list[dict]:
    return [s.model_dump() for s in segmenti().segmenti_default]


def segmenti_elettorato(c: Candidato) -> list[dict]:
    """Segmenti di default limitati alle aree di voto dell'elettorato potenziale."""
    if not c.elettorato_potenziale:
        return segmenti_predefiniti()
    return [s for s in segmenti_predefiniti() if s["area_di_voto"] in c.elettorato_potenziale]
