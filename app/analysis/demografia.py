"""Indicatori demografici e pesi dei segmenti del laboratorio messaggi.

La tabella demografia contiene solo conteggi additivi; qui si calcolano gli indicatori
(rapporti tra somme), così il valore cittadino è coerente con quello delle aree.

Inferenza ecologica: gli indicatori descrivono i residenti di un'area, non chi ha votato.
Una correlazione tra un indicatore e un risultato elettorale non dice nulla sul
comportamento delle singole persone.

Uso: ``uv run python -m app.analysis.demografia --pesi`` calcola e salva i pesi dei segmenti.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from itertools import product

import duckdb
import numpy as np
import pandas as pd

from app.core import db
from app.core.config import impostazioni, segmenti

COMUNE = "Comune di Torino, Ufficio di statistica"
ISTAT = "ISTAT, Censimento permanente 2021"
ISTAT_TAVOLE = "ISTAT, IstatData (tavole comunali)"
MEF = "MEF - Dipartimento delle Finanze"
AREA_VIRTUALE = -1
AREA_COMUNE = 0
ETA_MAX = 120
ETICHETTA_ECOLOGICA = (
    "I dati descrivono i residenti di un'area, non chi ha votato: una correlazione tra "
    "un indicatore e un risultato non dice come hanno votato le singole persone."
)


def _eta(prefisso: str, da: int, a: int = ETA_MAX) -> list[str]:
    return [f"{prefisso}_eta_{e:03d}" for e in range(da, a + 1)]


CLASSI_CENS = ["00_04", "05_09", "10_14", "15_19", "20_24", "25_29", "30_34", "35_39", "40_44",
               "45_49", "50_54", "55_59", "60_64", "65_69", "70_74", "75_piu"]  # fmt: skip


def _cens_eta(prefisso: str, classi: list[str]) -> list[str]:
    return [f"{prefisso}_eta_{c}" for c in classi]


@dataclass(frozen=True)
class Formula:
    fonte: str
    anno: int
    numeratore: tuple[str, ...]
    denominatore: tuple[str, ...]
    fattore: float = 1.0
    stima: bool = False  # valore stimato (ripartizione), da dichiarare


@dataclass(frozen=True)
class Indicatore:
    chiave: str
    nome: str
    unita: str
    nota: str
    formule: dict[str, Formula] = field(default_factory=dict)  # livello -> formula


def _f(fonte, anno, num, den, fattore=1.0, stima=False) -> Formula:
    return Formula(fonte, anno, tuple(num), tuple(den), fattore, stima)


POP_COMUNE = _eta("pop", 0)
CENS_15_64 = _cens_eta("cens", CLASSI_CENS[3:13])
CENS_0_14 = _cens_eta("cens", CLASSI_CENS[:3])
CENS_65 = _cens_eta("cens", CLASSI_CENS[13:])
FAMIGLIE_COMUNE_TIPI = None  # le tipologie si leggono dal database (variabili famiglie_*)

INDICATORI: dict[str, Indicatore] = {
    i.chiave: i
    for i in [
        Indicatore(
            "popolazione",
            "Residenti",
            "persone",
            "Popolazione residente.",
            {
                "circoscrizione": _f(COMUNE, 2025, POP_COMUNE, []),
                "citta": _f(COMUNE, 2025, POP_COMUNE, []),
                "sezione": _f(ISTAT, 2021, ["cens_pop"], []),
            },
        ),
        Indicatore(
            "indice_vecchiaia",
            "Indice di vecchiaia",
            "anziani ogni 100 giovani",
            "Residenti di 65 anni e più ogni 100 residenti di 0-14 anni.",
            {
                "circoscrizione": _f(COMUNE, 2025, _eta("pop", 65), _eta("pop", 0, 14), 100),
                "citta": _f(COMUNE, 2025, _eta("pop", 65), _eta("pop", 0, 14), 100),
                "sezione": _f(ISTAT, 2021, CENS_65, CENS_0_14, 100),
            },
        ),
        Indicatore(
            "quota_stranieri",
            "Stranieri",
            "%",
            "Residenti con cittadinanza straniera sul totale dei residenti.",
            {
                "circoscrizione": _f(COMUNE, 2025, ["stranieri"], POP_COMUNE, 100),
                "citta": _f(COMUNE, 2025, ["stranieri"], POP_COMUNE, 100),
                "sezione": _f(ISTAT, 2021, ["cens_stranieri"], ["cens_pop"], 100),
            },
        ),
        Indicatore(
            "quota_laureati",
            "Titolo terziario",
            "%",
            "Residenti con laurea o titolo terziario sui residenti di 9 anni e più "
            "(ISTAT non pubblica per sezione la popolazione di 25 anni e più per titolo).",
            {
                lv: _f(ISTAT, 2021, ["cens_istr_terziario"], ["cens_pop_9piu"], 100)
                for lv in ("circoscrizione", "citta", "sezione")
            },
        ),
        Indicatore(
            "tasso_occupazione",
            "Tasso di occupazione 15-64",
            "%",
            "Occupati di 15-64 anni sui residenti di 15-64 anni.",
            {
                lv: _f(ISTAT, 2021, ["cens_occupati_15_64"], CENS_15_64, 100)
                for lv in ("circoscrizione", "citta", "sezione")
            },
        ),
        Indicatore(
            "reddito_medio",
            "Reddito medio dichiarato",
            "euro",
            "Reddito complessivo IRPEF diviso per i contribuenti che lo dichiarano. "
            "Per aree e sezioni è stimato ripartendo i CAP in base alla popolazione.",
            {
                "circoscrizione": _f(
                    MEF,
                    2024,
                    ["mef_reddito_complessivo_eur"],
                    ["mef_reddito_complessivo_n"],
                    stima=True,
                ),
                "sezione": _f(
                    MEF,
                    2024,
                    ["mef_reddito_complessivo_eur"],
                    ["mef_reddito_complessivo_n"],
                    stima=True,
                ),
                "citta": _f(
                    MEF, 2024, ["mef_reddito_complessivo_eur"], ["mef_reddito_complessivo_n"]
                ),
            },
        ),
        Indicatore(
            "dimensione_famiglie",
            "Componenti per famiglia",
            "persone",
            "Residenti in famiglia diviso per il numero di famiglie.",
            {
                lv: _f(ISTAT, 2021, ["cens_pop"], ["cens_famiglie"])
                for lv in ("circoscrizione", "citta", "sezione")
            },
        ),
    ]
}


def _filtro_aree(livello: str, fonte: str) -> tuple[str, str]:
    """Espressione del codice area e condizione sulle aree per livello e fonte."""
    if livello == "citta":
        if fonte == MEF:
            return "'Torino'", f"d.area_id = {AREA_COMUNE}"
        aree = "(SELECT id FROM area WHERE tipo = 'circoscrizione')"
        return "'Torino'", f"(d.area_id IN {aree} OR d.area_id = {AREA_VIRTUALE})"
    return "a.codice", f"a.tipo = '{livello}'"


def valori(
    con: duckdb.DuckDBPyConnection, chiave: str, livello: str, come: str | None = None
) -> pd.DataFrame:
    """Valore dell'indicatore per area: colonne area, valore, numeratore, denominatore.

    ``come``: usa la formula (fonte e anno) di un altro livello. Serve per il confronto
    cittadino di una sezione: valori(con, k, "citta", come="sezione") usa i dati ISTAT 2021.
    """
    ind = INDICATORI[chiave]
    if (come or livello) not in ind.formule:
        raise ValueError(f"{ind.nome}: livello {come or livello} non disponibile")
    f = ind.formule[come or livello]
    codice, condizione = _filtro_aree(livello, f.fonte)
    num = list(f.numeratore)
    den = list(f.denominatore)
    df = (
        con.execute(
            f"""
        SELECT {codice} AS codice_area,
               sum(valore) FILTER (variabile IN (SELECT unnest(?::VARCHAR[]))) AS numeratore,
               sum(valore) FILTER (variabile IN (SELECT unnest(?::VARCHAR[]))) AS denominatore
        FROM demografia d LEFT JOIN area a ON a.id = d.area_id
        WHERE d.fonte = ? AND d.anno = ? AND {condizione}
        GROUP BY 1 ORDER BY try_cast(codice_area AS INTEGER), codice_area
        """,
            [num, den or ["__nessuna__"], f.fonte, f.anno],
        )
        .df()
        .rename(columns={"codice_area": "area"})
    )
    if den:
        df["valore"] = df["numeratore"] / df["denominatore"].replace(0, np.nan) * f.fattore
    else:
        df["valore"] = df["numeratore"]
    return df


def piramide(con: duckdb.DuckDBPyConnection, livello: str, codice: str = "Torino") -> pd.DataFrame:
    """Residenti per classe d'età quinquennale e sesso: colonne classe, maschi, femmine."""
    if livello == "sezione":
        righe = con.execute(
            "SELECT variabile, valore FROM demografia d JOIN area a ON a.id = d.area_id "
            "WHERE a.tipo = 'sezione' AND a.codice = ? AND d.fonte = ? "
            "AND (variabile LIKE 'cens_m_eta_%' OR variabile LIKE 'cens_f_eta_%')",
            [codice, ISTAT],
        ).fetchall()
        out = {}
        for var, v in righe:
            sesso = "maschi" if var.startswith("cens_m") else "femmine"
            classe = var.split("_eta_")[1].replace("_piu", "+").replace("_", "-")
            out.setdefault(classe, {"maschi": 0.0, "femmine": 0.0})[sesso] += v
        df = pd.DataFrame.from_dict(out, orient="index").reset_index(names="classe")
        return df.sort_values("classe").reset_index(drop=True), ISTAT, 2021
    _, condizione = _filtro_aree(livello, COMUNE)
    if livello == "circoscrizione":
        condizione += " AND a.codice = ?"
        parametri = [COMUNE, codice]
    else:
        parametri = [COMUNE]
    righe = con.execute(
        "SELECT variabile, sum(valore) FROM demografia d LEFT JOIN area a ON a.id = d.area_id "
        f"WHERE d.fonte = ? AND {condizione} "
        "AND (variabile LIKE 'pop_m_eta_%' OR variabile LIKE 'pop_f_eta_%') GROUP BY variabile",
        parametri,
    ).fetchall()
    out: dict[int, dict[str, float]] = {}
    for var, v in righe:
        eta = int(var[-3:])
        classe = min(eta // 5 * 5, 100)
        sesso = "maschi" if var.startswith("pop_m") else "femmine"
        out.setdefault(classe, {"maschi": 0.0, "femmine": 0.0})[sesso] += v
    df = pd.DataFrame.from_dict(out, orient="index").sort_index()
    df.index = [f"{c}-{c + 4}" if c < 100 else "100+" for c in df.index]
    return df.reset_index(names="classe"), COMUNE, 2025


def piramide_istat(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Piramide cittadina dal censimento 2021 (somma delle circoscrizioni), per confrontarla
    con quella delle sezioni elettorali, che hanno solo dati ISTAT."""
    righe = con.execute(
        "SELECT variabile, sum(valore) FROM demografia d JOIN area a ON a.id = d.area_id "
        "WHERE a.tipo = 'circoscrizione' AND d.fonte = ? "
        "AND (variabile LIKE 'cens_m_eta_%' OR variabile LIKE 'cens_f_eta_%') GROUP BY 1",
        [ISTAT],
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for var, v in righe:
        sesso = "maschi" if var.startswith("cens_m") else "femmine"
        classe = var.split("_eta_")[1].replace("_piu", "+").replace("_", "-")
        out.setdefault(classe, {"maschi": 0.0, "femmine": 0.0})[sesso] += v
    df = pd.DataFrame.from_dict(out, orient="index").reset_index(names="classe")
    return df.sort_values("classe").reset_index(drop=True)


SOGLIA_RESIDENTI_SEZIONE = 100


def popolazione_sezioni(con: duckdb.DuckDBPyConnection) -> pd.Series:
    return valori(con, "popolazione", "sezione").set_index("area")["valore"]


# --- pesi dei segmenti ------------------------------------------------------

CONDIZIONI_ISTAT = ["occupato", "in_cerca", "pensionato", "studente", "casalingo"]
CLASSI_ISTAT = {"15_24": (15, 24), "25_49": (25, 49), "50_64": (50, 64), "65_piu": (65, ETA_MAX)}
MAPPA_CONDIZIONE = {  # condizioni di segmenti.yaml -> condizione ISTAT
    "studente": "studente",
    "lavoratore dipendente": "occupato",
    "lavoratore autonomo": "occupato",
    "pensionato": "pensionato",
    "in cerca di lavoro": "in_cerca",
    "casalingo/a": "casalingo",
}


def _fascia(eta: str) -> tuple[int, int]:
    if eta.endswith("+"):
        return int(eta[:-1]), ETA_MAX
    da, a = eta.split("-")
    return int(da), int(a)


def condizioni_per_fascia(
    tavola: pd.DataFrame, pop_eta: pd.Series, fasce: list[str]
) -> pd.DataFrame:
    """Quote di condizione professionale per fascia d'età dei segmenti (righe che sommano a 1).

    ``tavola``: quote per classe ISTAT (righe 15_24, 25_49, 50_64, 65_piu; colonne
    CONDIZIONI_ISTAT, già senza "altra condizione"). ``pop_eta``: residenti per età singola.
    Ogni età eredita le quote della sua classe ISTAT; la fascia è la media pesata per età.
    """
    righe = {}
    for fascia in fasce:
        da, a = _fascia(fascia)
        somma = pd.Series(0.0, index=tavola.columns)
        for classe, (cda, ca) in CLASSI_ISTAT.items():
            peso = pop_eta.loc[max(da, cda) : min(a, ca)].sum() if max(da, cda) <= min(a, ca) else 0
            somma += tavola.loc[classe] * peso
        righe[fascia] = somma / somma.sum()
    return pd.DataFrame(righe).T


def aggiusta_occupazione(
    quote: pd.DataFrame, rapporto: float, fasce_lavoro: list[str]
) -> pd.DataFrame:
    """Scala la quota di occupati delle fasce in età da lavoro per il rapporto tra il tasso di
    occupazione dell'area e quello cittadino; le altre condizioni si riscalano in proporzione,
    così ogni riga continua a sommare a 1. È un raking con un solo margine (gli occupati)."""
    q = quote.copy()
    for fascia in fasce_lavoro:
        occ = min(q.loc[fascia, "occupato"] * rapporto, 0.98)
        resto = 1 - q.loc[fascia, "occupato"]
        altre = [c for c in q.columns if c != "occupato"]
        q.loc[fascia, altre] = q.loc[fascia, altre] * ((1 - occ) / resto if resto > 0 else 0)
        q.loc[fascia, "occupato"] = occ
    return q


def quote_voto(con: duckdb.DuckDBPyConnection, eid: int, aree_voto: list[str]) -> pd.DataFrame:
    """Quote sugli elettori per circoscrizione: aree di voto dei segmenti (righe che sommano a 1).

    Comunali: voti ai candidati sindaco (comprendono chi vota solo il sindaco); altre elezioni:
    voti di lista. "altro" si ripartisce in proporzione sulle aree politiche; bianche, nulle e
    non votanti formano l'astensione (ultima area di voto).
    """
    tipo, alias = con.execute(
        "SELECT tipo, CASE WHEN tipo = 'comunali' THEN 'candidato' ELSE 'lista' END "
        "FROM elezione WHERE id = ?",
        [eid],
    ).fetchone()
    filtro = (
        "r.tipo_soggetto = 'candidato_sindaco'"
        if alias == "candidato"
        else "r.tipo_soggetto = 'lista'"
    )
    voti = (
        con.execute(
            f"""
        SELECT sa.circoscrizione AS circ, a.area_politica AS area, sum(r.voti) AS voti
        FROM risultato r JOIN elezione e ON e.id = r.elezione_id
        JOIN sezione_area sa ON sa.sezione = r.sezione AND sa.anno = year(e.data)
        JOIN lista_alias a ON a.elezione_id = r.elezione_id AND a.tipo = ?
            AND a.soggetto = r.soggetto
        WHERE r.elezione_id = ? AND {filtro}
        GROUP BY ALL
        """,
            [alias, eid],
        )
        .df()
        .pivot_table(index="circ", columns="area", values="voti", aggfunc="sum", fill_value=0)
    )
    elettori = (
        con.execute(
            "SELECT sa.circoscrizione, sum(f.elettori) FROM affluenza f "
            "JOIN elezione e ON e.id = f.elezione_id "
            "JOIN sezione_area sa ON sa.sezione = f.sezione AND sa.anno = year(e.data) "
            "WHERE f.elezione_id = ? GROUP BY 1",
            [eid],
        )
        .df()
        .set_index("circoscrizione")
        .iloc[:, 0]
    )
    politiche, astensione = aree_voto[:-1], aree_voto[-1]
    out = pd.DataFrame(index=voti.index)
    validi = voti[[c for c in politiche if c in voti]].sum(axis=1)
    altro = voti.get("altro", 0)
    for c in politiche:
        v = voti.get(c, 0)
        out[c] = (v + altro * v / validi) / elettori.reindex(voti.index)
    out[astensione] = 1 - out[politiche].sum(axis=1)
    if (out < -1e-9).any().any():
        raise ValueError(f"Quote di voto negative per l'elezione {eid}")
    return out.clip(lower=0).div(out.clip(lower=0).sum(axis=1), axis=0)


def _elezione_id(con: duckdb.DuckDBPyConnection, chiave: str) -> int:
    from app.ingest.elezioni.consultazioni import PER_CHIAVE

    c = PER_CHIAVE[chiave]
    riga = con.execute(
        "SELECT id FROM elezione WHERE tipo = ? AND data = ? AND turno = ?",
        [c.tipo, c.data, c.turno],
    ).fetchone()
    if not riga:
        raise ValueError(f"Elezione {chiave} non caricata")
    return riga[0]


def pesi_segmenti(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Pesi per circoscrizione, variante e segmento (fascia × condizione × area di voto).

    Colonne: circoscrizione, variante, fascia_eta, condizione, area_di_voto, peso.
    Ipotesi: dentro una circoscrizione l'area di voto è indipendente da età e condizione.
    """
    cfg = segmenti()
    fasce, condizioni, aree_voto = cfg.fasce_eta, cfg.condizione, cfg.area_di_voto

    # Popolazione per età singola (Comune) per circoscrizione e città.
    pop = (
        con.execute(
            "SELECT a.codice AS circ, CAST(right(d.variabile, 3) AS INTEGER) AS eta, d.valore "
            "FROM demografia d JOIN area a ON a.id = d.area_id "
            "WHERE d.fonte = ? AND a.tipo = 'circoscrizione' AND d.variabile LIKE 'pop_eta_%'",
            [COMUNE],
        )
        .df()
        .pivot_table(index="eta", columns="circ", values="valore", aggfunc="sum", fill_value=0)
    )

    # Tavola comunale ISTAT: condizione per classe d'età (senza "altra condizione").
    tav = con.execute(
        "SELECT variabile, valore FROM demografia "
        "WHERE fonte = ? AND variabile LIKE 'istat_cond_%'",
        [ISTAT_TAVOLE],
    ).df()
    tav[["cond", "classe"]] = tav["variabile"].str.extract(r"istat_cond_(.+)_eta_(.+)")
    tavola = tav.pivot_table(index="classe", columns="cond", values="valore")[CONDIZIONI_ISTAT]
    tavola = tavola.div(tavola.sum(axis=1), axis=0)
    posizione = dict(
        con.execute(
            "SELECT variabile, valore FROM demografia "
            "WHERE fonte = ? AND variabile LIKE 'istat_occupati_%'",
            [ISTAT_TAVOLE],
        ).fetchall()
    )
    quota_autonomi = posizione["istat_occupati_indipendenti"] / posizione["istat_occupati_totale"]

    occ = valori(con, "tasso_occupazione", "circoscrizione").set_index("area")["valore"]
    occ_citta = valori(con, "tasso_occupazione", "citta")["valore"].iloc[0]
    fasce_lavoro = [f for f in fasce if _fascia(f)[1] <= 64]

    voto = {
        variante: sum(quote_voto(con, _elezione_id(con, k), aree_voto) for k in chiavi)
        / len(chiavi)
        for variante, chiavi in cfg.pesi_voto.varianti.items()
    }

    righe = []
    for circ in pop.columns:
        pop_eta = pop[circ]
        p_fascia = pd.Series({f: pop_eta.loc[_fascia(f)[0] : _fascia(f)[1]].sum() for f in fasce})
        p_fascia = p_fascia / p_fascia.sum()
        q = condizioni_per_fascia(tavola, pop_eta, fasce)
        q = aggiusta_occupazione(q, occ[circ] / occ_citta, fasce_lavoro)
        for variante, quote in voto.items():
            for fascia, cond, area in product(fasce, condizioni, aree_voto):
                p_cond = q.loc[fascia, MAPPA_CONDIZIONE[cond]]
                if cond == "lavoratore dipendente":
                    p_cond *= 1 - quota_autonomi
                elif cond == "lavoratore autonomo":
                    p_cond *= quota_autonomi
                peso = p_fascia[fascia] * p_cond * quote.loc[circ, area]
                righe.append((circ, variante, fascia, cond, area, float(peso)))
    return pd.DataFrame(
        righe,
        columns=["circoscrizione", "variante", "fascia_eta", "condizione", "area_di_voto", "peso"],
    )


def salva_pesi(con: duckdb.DuckDBPyConnection, pesi: pd.DataFrame, anno: int = 2025) -> int:
    """Scrive segmento (definizioni stabili, riusate tra i ricalcoli) e segmento_peso."""
    esistenti = {
        json.dumps(json.loads(d), sort_keys=True): i
        for i, d in con.execute("SELECT id, definizione FROM segmento").fetchall()
    }
    circ_ids = dict(
        con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall()
    )
    con.execute("BEGIN")
    try:
        ids = {}
        for chiave in (
            pesi[["fascia_eta", "condizione", "area_di_voto"]]
            .drop_duplicates()
            .itertuples(index=False)
        ):
            definizione = json.dumps(chiave._asdict(), sort_keys=True)
            if definizione not in esistenti:
                (esistenti[definizione],) = con.execute(
                    "INSERT INTO segmento (definizione) VALUES (?) RETURNING id", [definizione]
                ).fetchone()
            ids[tuple(chiave)] = esistenti[definizione]
        righe = pesi.assign(
            segmento_id=[
                ids[(r.fascia_eta, r.condizione, r.area_di_voto)] for r in pesi.itertuples()
            ],
            area_id=pesi["circoscrizione"].map(circ_ids),
            anno=anno,
        )
        con.execute("DELETE FROM segmento_peso WHERE anno = ?", [anno])
        con.register("_pesi", righe)
        con.execute(
            "INSERT INTO segmento_peso (segmento_id, area_id, anno, variante, peso) "
            "SELECT segmento_id, area_id, anno, variante, peso FROM _pesi"
        )
        con.unregister("_pesi")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(righe)


def main() -> None:
    parser = argparse.ArgumentParser(description="Indicatori demografici e pesi dei segmenti")
    parser.add_argument("--pesi", action="store_true", help="calcola e salva i pesi dei segmenti")
    args = parser.parse_args()
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        for chiave, ind in INDICATORI.items():
            v = valori(con, chiave, "citta")["valore"].iloc[0]
            print(f"{ind.nome:30} Torino: {v:,.2f} {ind.unita}")
        if args.pesi:
            pesi = pesi_segmenti(con)
            n = salva_pesi(con, pesi)
            somme = pesi.groupby(["circoscrizione", "variante"])["peso"].sum()
            print(
                f"Pesi salvati: {n}; somma per area e variante "
                f"tra {somme.min():.6f} e {somme.max():.6f}"
            )


if __name__ == "__main__":
    main()
