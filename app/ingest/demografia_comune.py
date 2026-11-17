"""Ingest della popolazione residente per circoscrizione dall'Ufficio di statistica del Comune.

Fonte: Città di Torino, aperto.comune.torino.it (licenza CC BY 4.0), dati al 31/12/2025.
I file hanno una riga per voce (età, tipologia di famiglia, stato civile) e una colonna per
circoscrizione (``circ_1`` … ``circ_8``) più ``residenza_virtuale``: residenti senza fissa
dimora iscritti a un indirizzo fittizio, che contano nel totale cittadino ma in nessuna
circoscrizione. In ``demografia`` stanno con area_id = -1.

Uso: ``uv run python -m app.ingest.demografia_comune``
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from app.core import db
from app.core.codici import normalizza_circoscrizione
from app.core.config import impostazioni
from app.ingest._comune import registra_caricamento, scarica
from app.ingest.elezioni.riepilogo import decodifica

FONTE = "comune_demografia"
ETICHETTA_FONTE = "Comune di Torino, Ufficio di statistica"
ANNO = 2025
VIRTUALE = "virtuale"
AREA_VIRTUALE = -1


class ErroreIngest(RuntimeError):
    pass


@dataclass(frozen=True)
class FileComune:
    url: str
    nome: str  # nome con cui salvarlo in data/raw
    forma: str  # "matrice" (voci x circoscrizioni) oppure "per_circoscrizione"
    prefisso: str  # prefisso delle variabili
    eta: bool = False  # la prima colonna è un'età: variabile <prefisso>_eta_NNN


MEDIA = "https://www.comune.torino.it/media/"
# (numero risorsa, nome file, forma, prefisso variabili, prima colonna = età)
_FILE = [
    ("9707", "B1_pop_eta_2025.csv", "matrice", "pop", True),
    ("9708", "B2_pop_eta_maschi_2025.csv", "matrice", "pop_m", True),
    ("9709", "B3_pop_eta_femmine_2025.csv", "matrice", "pop_f", True),
    ("9692", "pop_genere_2025.csv", "per_circoscrizione", "genere", False),
    ("9735", "E1_stranieri_sesso_2025.csv", "per_circoscrizione", "stranieri", False),
    ("9738", "E4_stranieri_eta_2025.csv", "matrice", "stranieri", True),
    ("9722", "famiglie_tipologia_2025.csv", "matrice", "famiglie", False),
    ("9724", "D3_stato_civile_2025.csv", "matrice", "stato_civile", False),
]
FILE = tuple(FileComune(MEDIA + n, nome, forma, pref, eta) for n, nome, forma, pref, eta in _FILE)


def slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _codice_colonna(nome: str) -> str | None:
    n = nome.strip().lower()
    if n == "residenza_virtuale" or n == "residenza virtuale":
        return VIRTUALE
    if m := re.fullmatch(r"circ_?(\d)", n):
        return normalizza_circoscrizione(m.group(1))
    return None


def _righe(dati: bytes) -> list[list[str]]:
    testo = decodifica(dati)
    return [r for r in csv.reader(io.StringIO(testo), delimiter=";") if any(c.strip() for c in r)]


def leggi(f: FileComune, dati: bytes) -> pd.DataFrame:
    """Restituisce righe (area, variabile, valore); area = codice circoscrizione o 'virtuale'."""
    righe = _righe(dati)
    out = []
    if f.forma == "matrice":
        intestazione = righe[0]
        colonne = [_codice_colonna(c) for c in intestazione[1:]]
        if sorted(c for c in colonne if c and c != VIRTUALE) != [str(i) for i in range(1, 9)]:
            raise ErroreIngest(f"{f.nome}: colonne delle circoscrizioni non riconosciute")
        for r in righe[1:]:
            voce = r[0].strip()
            variabile = (
                f"{f.prefisso}_eta_{int(voce):03d}" if f.eta else f"{f.prefisso}_{slug(voce)}"
            )
            for codice, valore in zip(colonne, r[1:], strict=False):
                if codice and valore.strip():
                    out.append((codice, variabile, float(valore)))
    else:
        # Una riga per circoscrizione: "circoscrizione";"femmine";"maschi"[;totale]
        for r in righe[1:]:
            area = r[0].strip().lower()
            codice = VIRTUALE if "virtuale" in area else normalizza_circoscrizione(area)
            femmine, maschi = float(r[1]), float(r[2])
            out.append((codice, f"{f.prefisso}_f", femmine))
            out.append((codice, f"{f.prefisso}_m", maschi))
            if len(r) > 3 and r[3].strip() and float(r[3]) != femmine + maschi:
                raise ErroreIngest(f"{f.nome}: totale diverso da femmine + maschi in {area}")
            out.append((codice, f"{f.prefisso}", femmine + maschi))
    return pd.DataFrame(out, columns=["area", "variabile", "valore"])


def controlla(tutto: pd.DataFrame) -> None:
    """Coerenza interna dei file.

    Età totali = maschi + femmine = file per genere; stranieri per età = totale stranieri.
    """

    def somma(prefisso: str) -> pd.Series:
        sel = tutto[tutto.variabile.str.match(rf"{prefisso}_eta_\d{{3}}$")]
        return sel.groupby("area")["valore"].sum()

    tot, m, f = somma("pop"), somma("pop_m"), somma("pop_f")
    genere = tutto[tutto.variabile.isin(["genere_m", "genere_f"])].groupby("area")["valore"].sum()
    if not (tot.equals(m + f)):
        raise ErroreIngest(
            f"Popolazione per età diversa da maschi + femmine:\n{pd.concat([tot, m + f], axis=1)}"
        )
    if not tot.equals(genere.reindex(tot.index)):
        raise ErroreIngest(
            f"Popolazione per età diversa dal file per genere:\n{pd.concat([tot, genere], axis=1)}"
        )
    stranieri_eta = somma("stranieri")
    stranieri = tutto[tutto.variabile == "stranieri"].set_index("area")["valore"]
    if not stranieri_eta.equals(stranieri.reindex(stranieri_eta.index)):
        raise ErroreIngest("Stranieri per età diversi dal totale per sesso")


def scrivi(con: duckdb.DuckDBPyConnection, tutto: pd.DataFrame, anno: int = ANNO) -> int:
    ids = dict(con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall())
    if len(ids) != 8:
        raise ErroreIngest("Circoscrizioni non caricate: eseguire prima app.ingest.circoscrizioni")
    ids[VIRTUALE] = AREA_VIRTUALE
    # Il file per genere serve solo da controllo: duplicherebbe la popolazione per età.
    dati = tutto[~tutto.variabile.str.startswith("genere_")].copy()
    dati["area_id"] = dati["area"].map(ids)
    dati["anno"] = anno
    dati["fonte"] = ETICHETTA_FONTE
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM demografia WHERE fonte = ? AND anno = ?", [ETICHETTA_FONTE, anno])
        con.register("_dem", dati)
        con.execute(
            "INSERT INTO demografia (area_id, anno, variabile, valore, fonte) "
            "SELECT area_id, anno, variabile, valore, fonte FROM _dem"
        )
        con.unregister("_dem")
        registra_caricamento(con, FONTE, len(dati))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(dati)


def leggi_tutto(scaricatore=scarica) -> pd.DataFrame:
    parti = []
    for f in FILE:
        percorso: Path = scaricatore(f.url, FONTE, nome_file=f.nome)
        parti.append(leggi(f, percorso.read_bytes()))
    return pd.concat(parti, ignore_index=True)


def main() -> None:
    tutto = leggi_tutto()
    controlla(tutto)
    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        n = scrivi(con, tutto)
    pop = tutto[tutto.variabile.str.match(r"pop_eta_\d{3}$")].groupby("area")["valore"].sum()
    print(f"Caricate {n} righe. Residenti al 31/12/{ANNO}: {int(pop.sum()):,}".replace(",", "."))
    for area, v in pop.items():
        print(f"  {area:10} {int(v):>8,}".replace(",", "."))


if __name__ == "__main__":
    main()
