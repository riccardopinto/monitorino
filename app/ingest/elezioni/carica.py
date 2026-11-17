"""Caricamento di una consultazione in DuckDB: elezione, affluenza, risultato, sezione_area."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from app.core.config import AreePolitiche, aree_politiche, scostamenti_noti
from app.ingest._comune import registra_caricamento, scarica
from app.ingest.elezioni import eligendo
from app.ingest.elezioni.consultazioni import BASE, Consultazione, File
from app.ingest.elezioni.riepilogo import Riepilogo, leggi_riepilogo


class ErroreIngest(RuntimeError):
    pass


@dataclass
class Letto:
    file: File
    nome: str  # percorso o membro dello zip, per i messaggi
    riepilogo: Riepilogo


def _leggi(file: File, percorso: Path) -> Iterator[Letto]:
    if file.membri is None:
        yield Letto(file, file.percorso, leggi_riepilogo(percorso))
        return
    with zipfile.ZipFile(percorso) as zf:
        membri = sorted(n for n in zf.namelist() if re.fullmatch(file.membri, n))
        if not membri:
            raise ErroreIngest(f"Nessun file {file.membri} in {file.percorso}")
        for m in membri:
            yield Letto(file, f"{file.percorso}!{m}", leggi_riepilogo(zf.read(m)))


def leggi_consultazione(c: Consultazione, scaricatore=scarica) -> list[Letto]:
    letti = []
    scaricati: dict[str, Path] = {}
    for f in c.file:
        if f.percorso not in scaricati:
            scaricati[f.percorso] = scaricatore(BASE + f.percorso, c.fonte)
        letti.extend(_leggi(f, scaricati[f.percorso]))
    return letti


def _controlla_totali(letto: Letto) -> None:
    """La somma per sezione deve coincidere con la riga TOTALE del file, quando c'è."""
    r = letto.riepilogo
    if not r.totale_voti:
        return
    somme = r.voti.groupby("numero")["voti"].sum().to_dict()
    diverse = {n: (somme.get(n), v) for n, v in r.totale_voti.items() if somme.get(n) != v}
    if diverse:
        raise ErroreIngest(f"{letto.nome}: somme per sezione diverse dal TOTALE: {diverse}")


def tabelle(letti: list[Letto]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restituisce affluenza (una riga per sezione) e risultati in formato lungo."""
    affluenze = [x.riepilogo.affluenza for x in letti if x.file.affluenza]
    if not affluenze:
        raise ErroreIngest("Nessun file fornisce l'affluenza")
    affluenza = pd.concat(affluenze, ignore_index=True)
    doppie = affluenza["sezione"][affluenza["sezione"].duplicated()]
    if not doppie.empty:
        raise ErroreIngest(f"Sezioni ripetute nell'affluenza: {sorted(set(doppie))[:10]}")

    # Nome delle liste per numero, per assegnare le preferenze. Nelle circoscrizionali la
    # numerazione è propria di ogni circoscrizione: la chiave include lo zip.
    liste: dict[tuple[str, int], str] = {}
    for x in letti:
        if x.file.tipo_soggetto == "lista":
            for s in x.riepilogo.soggetti:
                liste[(x.file.percorso, s.numero)] = s.nome

    parti = []
    for x in letti:
        _controlla_totali(x)
        v = x.riepilogo.voti
        gruppo = ""
        if x.file.tipo_soggetto == "preferenza":
            lista = x.riepilogo.lista
            if lista is None:
                raise ErroreIngest(f"{x.nome}: lista delle preferenze non indicata")
            # Il nome dal file delle liste, così preferenze e voti di lista coincidono.
            gruppo = liste.get((x.file.percorso, lista.numero), lista.nome)
            v = v[v["voti"] > 0]  # le preferenze nulle non si salvano: assenza = 0
        parti.append(
            pd.DataFrame(
                {
                    "sezione": v["sezione"],
                    "tipo_soggetto": x.file.tipo_soggetto,
                    "soggetto": v["soggetto"],
                    "gruppo": gruppo,
                    "voti": v["voti"].astype(int),
                }
            )
        )
    risultati = pd.concat(parti, ignore_index=True)
    chiave = ["sezione", "tipo_soggetto", "gruppo", "soggetto"]
    doppie = risultati[risultati.duplicated(chiave, keep=False)]
    if not doppie.empty:
        raise ErroreIngest(f"Risultati ripetuti: {doppie.head().to_dict('records')}")
    return affluenza, risultati


def scrivi(
    con: duckdb.DuckDBPyConnection,
    c: Consultazione,
    affluenza: pd.DataFrame,
    risultati: pd.DataFrame,
    alias: pd.DataFrame | None = None,
    totali_ufficiali: list[tuple[str, str, int]] | None = None,
) -> int:
    """Sostituisce i dati della consultazione. Restituisce l'id dell'elezione.

    Se ci sono totali ufficiali e le somme per sezione non coincidono, annulla tutto.
    """
    con.execute("BEGIN")
    try:
        riga = con.execute(
            "SELECT id FROM elezione WHERE tipo = ? AND data = ? AND turno = ?",
            [c.tipo, c.data, c.turno],
        ).fetchone()
        if riga:
            eid = riga[0]
            for t in ("affluenza", "risultato", "lista_alias", "totale_ufficiale"):
                con.execute(f"DELETE FROM {t} WHERE elezione_id = ?", [eid])
            con.execute("UPDATE elezione SET nome = ? WHERE id = ?", [c.nome, eid])
        else:
            (eid,) = con.execute(
                "INSERT INTO elezione (tipo, data, turno, nome) VALUES (?, ?, ?, ?) RETURNING id",
                [c.tipo, c.data, c.turno, c.nome],
            ).fetchone()

        aff = affluenza.assign(elezione_id=eid)
        con.register("_aff", aff)
        con.execute(
            "INSERT INTO affluenza (elezione_id, sezione, elettori, votanti, schede_bianche, "
            "schede_nulle, schede_contestate, voti_validi) "
            "SELECT elezione_id, sezione, elettori, votanti, schede_bianche, schede_nulle, "
            "schede_contestate, voti_validi FROM _aff"
        )
        con.unregister("_aff")

        ris = risultati.assign(elezione_id=eid)
        con.register("_ris", ris)
        con.execute(
            "INSERT INTO risultato (elezione_id, sezione, tipo_soggetto, soggetto, gruppo, voti) "
            "SELECT elezione_id, sezione, tipo_soggetto, soggetto, gruppo, voti FROM _ris"
        )
        con.unregister("_ris")

        # Corrispondenza sezione -> circoscrizione per l'anno: fanno fede i file dei risultati.
        mappa = affluenza[["sezione", "circoscrizione"]].dropna().assign(anno=c.data.year)
        con.register("_map", mappa)
        conflitti = con.execute(
            "SELECT m.sezione, m.circoscrizione, s.circoscrizione FROM _map m "
            "JOIN sezione_area s ON s.sezione = m.sezione AND s.anno = m.anno "
            "WHERE s.circoscrizione <> m.circoscrizione"
        ).fetchall()
        if conflitti:
            raise ErroreIngest(
                f"Circoscrizione diversa per la stessa sezione e anno: {conflitti[:5]}"
            )
        con.execute(
            "INSERT OR REPLACE INTO sezione_area (sezione, anno, circoscrizione) "
            "SELECT sezione, anno, circoscrizione FROM _map"
        )
        con.unregister("_map")

        if alias is not None and not alias.empty:
            con.register("_alias", alias.assign(elezione_id=eid))
            con.execute(
                "INSERT INTO lista_alias (elezione_id, tipo, soggetto, forza_politica, "
                "area_politica, coalizione) SELECT elezione_id, tipo, soggetto, forza_politica, "
                "area_politica, coalizione FROM _alias"
            )
            con.unregister("_alias")

        if totali_ufficiali:
            con.executemany(
                "INSERT INTO totale_ufficiale (elezione_id, voce, soggetto, valore, fonte) "
                "VALUES (?, ?, ?, ?, ?)",
                [(eid, voce, sogg, val, eligendo.FONTE) for voce, sogg, val in totali_ufficiali],
            )
            diverse = eligendo.non_previste(
                eligendo.differenze(con, eid), scostamenti_noti().get(c.chiave, {})
            )
            if diverse:
                raise ErroreIngest(
                    f"{c.nome}: somme per sezione diverse dai totali ufficiali Eligendo:\n  "
                    + "\n  ".join(diverse)
                )

        registra_caricamento(con, f"elezioni:{c.chiave}", len(risultati))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return eid


TIPI_CANDIDATO_CLASSIFICATI = ("candidato_sindaco", "candidato_presidente")


def alias(c: Consultazione, risultati: pd.DataFrame, aree: AreePolitiche) -> pd.DataFrame:
    """Classificazione di liste e candidati da config/aree_politiche.yaml.

    Ogni lista e ogni candidato sindaco o presidente deve avere una voce: se ne manca
    qualcuna l'ingest si ferma, così nessun soggetto resta senza area politica.
    """
    candidati, liste = aree.risolvi(c.chiave)
    righe = []
    mancanti = []
    for nome in sorted(risultati.loc[risultati.tipo_soggetto == "lista", "soggetto"].unique()):
        if nome not in liste:
            mancanti.append(f"lista {nome!r}")
            continue
        cl = liste[nome]
        righe.append(("lista", nome, cl.forza, cl.area, cl.coalizione))
    sel = risultati.tipo_soggetto.isin(TIPI_CANDIDATO_CLASSIFICATI)
    for nome in sorted(risultati.loc[sel, "soggetto"].unique()):
        if nome not in candidati:
            mancanti.append(f"candidato {nome!r}")
            continue
        righe.append(("candidato", nome, f"Coalizione {nome}", candidati[nome], nome))
    if mancanti:
        raise ErroreIngest(
            f"{c.chiave}: soggetti senza classificazione in config/aree_politiche.yaml: "
            + ", ".join(mancanti)
        )
    return pd.DataFrame(
        righe, columns=["tipo", "soggetto", "forza_politica", "area_politica", "coalizione"]
    )


def carica(
    con: duckdb.DuckDBPyConnection,
    c: Consultazione,
    scaricatore=scarica,
    *,
    aree: AreePolitiche | None = None,
    totali_ufficiali: bool = True,
) -> int:
    """Scarica, legge, classifica e scrive una consultazione.

    ``aree`` e ``totali_ufficiali`` servono ai test: di default si usano
    config/aree_politiche.yaml e i totali di Eligendo.
    """
    letti = leggi_consultazione(c, scaricatore)
    affluenza, risultati = tabelle(letti)
    classificazione = alias(c, risultati, aree or aree_politiche())
    ufficiali = eligendo.scarica_totali(c.chiave, scaricatore) if totali_ufficiali else None
    return scrivi(con, c, affluenza, risultati, classificazione, ufficiali)
