"""Totali ufficiali di Torino dagli open data del Ministero dell'Interno (Eligendo).

Fonte: https://elezionistorico.interno.gov.it, file su dait.interno.gov.it/documenti/opendata.
Sono dati per comune di tutta Italia: si estraggono le righe del comune di Torino.
Servono come controllo indipendente delle somme per sezione dei file del Comune.
I file contengono anche dati anagrafici dei candidati (luogo e data di nascita): non si salvano.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from dataclasses import dataclass

import duckdb

from app.ingest._comune import scarica
from app.ingest.elezioni.riepilogo import decodifica

FONTE = "eligendo"
BASE = "https://dait.interno.gov.it/documenti/opendata/"


@dataclass(frozen=True)
class Formato:
    zip: str
    membro: str
    elettori: str
    votanti: str
    bianche: str
    lista: str | None
    voti_lista: str | None
    cognome: str | None = None
    nome: str | None = None
    voti_candidato: str | None = None
    turno: str | None = None  # (colonna, valore) per i file con primo turno e ballottaggio
    valore_turno: str | None = None
    collegio: str | None = None  # politiche: iscritti e votanti sono per collegio uninominale


_COM16 = dict(
    zip="comunali/comunali-20160605.zip",
    membro="comunali-20160605.txt",
    elettori="ELETTORI",
    votanti="VOTANTI",
    bianche="SCHEDE_BIANCHE",
    lista="LISTA",
    voti_lista="VOTI_LISTA",
    cognome="COGNOME",
    nome="NOME",
    voti_candidato="VOTI_CANDIDATO",
    turno="TURNO",
)
_COM21 = dict(
    zip="comunali/comunali-20211003.zip",
    membro="comunali-20211003.txt",
    elettori="elettoritot",
    votanti="votantitot",
    bianche="skbianche",
    lista="DESCRLISTA",
    voti_lista="VOTILISTA",
    cognome="cognome",
    nome="nome",
    voti_candidato="VOTICANDIDSINDACO",
    turno="TURNO",
)
_POL = dict(
    elettori="ELETTORITOT",
    votanti="VOTANTITOT",
    bianche="SKBIANCHE",
    lista="DESCRLISTA",
    voti_lista="VOTILISTA",
    cognome="COGNOME",
    nome="NOME",
    voti_candidato="VOTICANDIDATO",
    collegio="COLLUNINOM",
)

FORMATI: dict[str, Formato] = {
    "comunali_2016": Formato(**_COM16, valore_turno="1"),
    # Al ballottaggio non si votano le liste: le righe ripetono i voti del primo turno.
    "comunali_2016_ballottaggio": Formato(
        **{**_COM16, "lista": None, "voti_lista": None}, valore_turno="2"
    ),
    "comunali_2021": Formato(**_COM21, valore_turno="1"),
    "comunali_2021_ballottaggio": Formato(
        **{**_COM21, "lista": None, "voti_lista": None}, valore_turno="2"
    ),
    "camera_2022": Formato(
        zip="camera/camera-20220925.zip", membro="camera2022_Italia_LivComune.csv", **_POL
    ),
    "senato_2022": Formato(
        zip="senato/senato-20220925.zip", membro="Senato_Italia_LivComune.csv", **_POL
    ),
    "europee_2019": Formato(
        zip="europee/europee-20190526.zip",
        membro="europee-20190526.txt",
        elettori="ELETTORI",
        votanti="VOTANTI",
        bianche="SCHEDEBIANCHE",
        lista="LISTA",
        voti_lista="VOTI_LISTA",
    ),
    "europee_2024": Formato(
        zip="europee/europee-20240609.zip",
        membro="EUROPEE_SCRUTINI&LISTE_ITALIA_LivComune.csv",
        elettori="ELETTORI",
        votanti="VOTANTI",
        bianche="NUMSCHEDEBIANCHE",
        lista="DESCLISTA",
        voti_lista="NUMVOTI",
    ),
    "regionali_2024": Formato(
        zip="regionali/regionali-20240609.zip",
        membro="regionali-20240609.csv",
        elettori="ELETTORITOT",
        votanti="VOTANTITOT",
        bianche="SKBIANCHE",
        lista="DESCRLISTA",
        voti_lista="VOTILISTA",
        cognome="COGNOME",
        nome="NOME",
        voti_candidato="VOTICANDIDATO",
    ),
}


def _righe_torino(dati: bytes) -> list[dict[str, str]]:
    lettore = csv.DictReader(io.StringIO(decodifica(dati)), delimiter=";")
    col = next(c for c in lettore.fieldnames or [] if c.upper() in ("COMUNE", "DESCCOMUNE"))
    return [r for r in lettore if r[col].strip().upper() == "TORINO"]


def totali(f: Formato, righe: list[dict[str, str]]) -> list[tuple[str, str, int]]:
    """(voce, soggetto, valore) per Torino: iscritti, votanti, bianche, liste, candidati."""
    if f.turno:
        righe = [r for r in righe if r[f.turno].strip() == f.valore_turno]
    if not righe:
        raise ValueError("Nessuna riga di Torino nel file Eligendo")

    # Iscritti e votanti si ripetono su ogni riga; nelle politiche valgono per collegio.
    per_collegio: dict[str, dict[str, str]] = {}
    for r in righe:
        per_collegio.setdefault(r[f.collegio].strip() if f.collegio else "", r)
    out = [
        (voce, "", sum(int(r[col]) for r in per_collegio.values()))
        for voce, col in (("iscritti", f.elettori), ("votanti", f.votanti), ("bianche", f.bianche))
    ]

    if f.lista and f.voti_lista:
        liste: dict[str, int] = {}
        visti = set()
        for r in righe:
            chiave = (r[f.collegio] if f.collegio else "", r[f.lista])
            if chiave in visti:  # nelle comunali la riga è per candidato e lista
                continue
            visti.add(chiave)
            liste[r[f.lista].strip()] = liste.get(r[f.lista].strip(), 0) + int(r[f.voti_lista])
        out += [("lista", nome, voti) for nome, voti in liste.items()]

    if f.cognome and f.voti_candidato:
        candidati: dict[tuple[str, str], int] = {}
        for r in righe:
            nome = f"{r[f.cognome].strip()} {r[f.nome].strip()}".strip()
            candidati[(r[f.collegio] if f.collegio else "", nome)] = int(r[f.voti_candidato])
        out += [("candidato", nome, voti) for (_, nome), voti in candidati.items()]
    return out


def scarica_totali(chiave: str, scaricatore=scarica) -> list[tuple[str, str, int]] | None:
    """Totali ufficiali della consultazione, o None se Eligendo non la copre."""
    f = FORMATI.get(chiave)
    if f is None:
        return None
    percorso = scaricatore(BASE + f.zip, FONTE)
    with zipfile.ZipFile(percorso) as zf:
        return totali(f, _righe_torino(zf.read(f.membro)))


def differenze(con: duckdb.DuckDBPyConnection, eid: int) -> dict[str, dict]:
    """Confronta le somme per sezione con i totali ufficiali salvati per l'elezione.

    Liste e candidati si confrontano come insiemi di valori (ordinati): i nomi nei file del
    Comune e del Ministero sono scritti in modo diverso, ma se ogni voce coincide i due
    elenchi di numeri sono identici. Restituisce solo le voci che differiscono.
    """
    uff = con.execute(
        "SELECT voce, soggetto, valore FROM totale_ufficiale WHERE elezione_id = ?", [eid]
    ).fetchall()
    if not uff:
        return {}
    out: dict[str, dict] = {}
    somme = dict(
        zip(
            ("iscritti", "votanti", "bianche"),
            con.execute(
                "SELECT sum(elettori), sum(votanti), sum(schede_bianche) FROM affluenza "
                "WHERE elezione_id = ?",
                [eid],
            ).fetchone(),
            strict=True,
        )
    )
    for voce in ("iscritti", "votanti", "bianche"):
        for _, _, valore in (u for u in uff if u[0] == voce):
            if somme[voce] != valore:
                out[voce] = {"ufficiale": valore, "sezioni": int(somme[voce])}

    tipi = {
        "lista": "('lista')",
        "candidato": "('candidato_sindaco', 'candidato_presidente', 'candidato_uninominale')",
    }
    for voce, filtro in tipi.items():
        ufficiali = sorted(v for vv, _, v in uff if vv == voce)
        if not ufficiali:
            continue
        nostri = sorted(
            r[0]
            for r in con.execute(
                f"SELECT sum(voti) FROM risultato WHERE elezione_id = ? AND tipo_soggetto IN "
                f"{filtro} GROUP BY soggetto",
                [eid],
            ).fetchall()
        )
        if nostri != ufficiali:
            out[voce] = {
                "solo_ufficiali": sorted((Counter(ufficiali) - Counter(nostri)).elements()),
                "solo_sezioni": sorted((Counter(nostri) - Counter(ufficiali)).elements()),
            }
    return out


def non_previste(diff: dict[str, dict], noti: dict[str, dict]) -> list[str]:
    """Differenze che non coincidono con quelle documentate in config/scostamenti_noti.yaml."""
    return [
        f"{voce}: {dettaglio} (documentate: {noti.get(voce)})"
        for voce, dettaglio in diff.items()
        if noti.get(voce) != dettaglio
    ]
