"""Parser dei "Riepiloghi per sezioni" pubblicati dal Comune su elezioni.comune.torino.it.

Tutti i file (sindaco, liste, preferenze, uninominali, circoscrizioni, 2016-2024) hanno:
- alcune righe di preambolo (titolo, "LISTA: N - nome", "SCRUTINATE n SEZIONI SU m");
- una riga di intestazione che inizia con "Sezione": prima le colonne fisse, poi per ogni
  soggetto il suo numero, il nome ed eventuali etichette ("Voti solo Sindaco");
- una riga per sezione: colonne fisse, poi i voti di ogni soggetto, separati da un campo
  vuoto. Un soggetto può avere più valori (voti, voti solo candidato): conta il primo;
- spesso una riga finale "TOTALE".
Varianti gestite: codifica UTF-8 o cp1252, valori con o senza virgolette, colonna
"Scrutinata" presente o assente, nomi diversi per le stesse colonne fisse.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.core.codici import normalizza_circoscrizione, normalizza_sezione


class ErroreFormato(ValueError):
    pass


@dataclass
class Soggetto:
    numero: int
    nome: str


@dataclass
class Riepilogo:
    titolo: str
    soggetti: list[Soggetto]
    affluenza: pd.DataFrame  # una riga per sezione, colonne in COLONNE_AFFLUENZA
    voti: pd.DataFrame  # sezione, numero, soggetto, voti
    lista: Soggetto | None = None  # per i file di preferenze: la lista a cui si riferiscono
    scrutinate: tuple[int, int] | None = None
    totale: dict[str, int | None] = field(default_factory=dict)  # riga TOTALE, se c'è
    totale_voti: dict[int, int] = field(default_factory=dict)  # numero soggetto -> voti


COLONNE_AFFLUENZA = [
    "sezione",
    "circoscrizione",
    "scrutinata",
    "elettori",
    "votanti",
    "schede_bianche",
    "schede_nulle",
    "schede_contestate",
    "voti_validi",
]


def decodifica(dati: bytes) -> str:
    """I file sono in UTF-8, alcuni in cp1252 (Windows)."""
    try:
        return dati.decode("utf-8")
    except UnicodeDecodeError:
        return dati.decode("cp1252")


def _campi(riga: str) -> list[str]:
    return next(csv.reader([riga], delimiter=";"))


def _colonna_fissa(nome: str) -> str | None:
    n = " ".join(nome.lower().split())
    if n == "sezione":
        return "sezione"
    if n == "scrutinata":
        return "scrutinata"
    if n == "circoscrizione":
        return "circoscrizione"
    if n == "totale iscritti":
        return "elettori"
    if n.startswith("votanti totali"):
        return "votanti"
    if n == "schede bianche":
        return "schede_bianche"
    if n == "schede nulle":
        return "schede_nulle"
    if "contestat" in n or "cont./non ass" in n:
        return "schede_contestate"
    if n == "voti validi":
        return "voti_validi"
    return None  # collegi, plesso, iscritti e votanti per sesso, voti solo candidato


def _intero(valore: str) -> int | None:
    v = valore.strip()
    return int(v) if v else None


def leggi_riepilogo(sorgente: Path | bytes) -> Riepilogo:
    dati = sorgente.read_bytes() if isinstance(sorgente, Path) else sorgente
    righe = decodifica(dati).splitlines()

    i_head = next(
        (i for i, r in enumerate(righe) if r.strip() and _campi(r)[0].strip() == "Sezione"), None
    )
    if i_head is None:
        raise ErroreFormato("Riga di intestazione 'Sezione' non trovata")

    preambolo = [r.strip().strip('"').strip() for r in righe[:i_head]]
    preambolo = [r for r in preambolo if r]
    titolo = preambolo[0] if preambolo else ""
    lista = None
    scrutinate = None
    for r in preambolo:
        if m := re.match(r"LISTA:\s*(\d+)\s*-\s*(.+)", r):
            lista = Soggetto(int(m.group(1)), m.group(2).strip())
        if m := re.search(r"SCRUTINATE\s+(\d+)\s+SEZIONI\s+SU\s+(\d+)", r):
            scrutinate = (int(m.group(1)), int(m.group(2)))

    intestazione = [c.strip() for c in _campi(righe[i_head])]
    n_fisse = next(
        (i for i, c in enumerate(intestazione) if re.fullmatch(r"\d+", c)), len(intestazione)
    )
    fisse = [_colonna_fissa(c) for c in intestazione[:n_fisse]]
    if "sezione" not in fisse:
        raise ErroreFormato("Colonna Sezione mancante")

    soggetti: list[Soggetto] = []
    resto = intestazione[n_fisse:]
    for i, token in enumerate(resto):
        if re.fullmatch(r"\d+", token) and i + 1 < len(resto):
            soggetti.append(Soggetto(int(token), " ".join(resto[i + 1].split())))
    if not soggetti:
        raise ErroreFormato("Nessun candidato o lista nell'intestazione")

    def scomponi(campi: list[str]) -> tuple[dict[str, int | str | None], list[int | None]]:
        valori: dict[str, int | str | None] = {}
        for nome, v in zip(fisse, campi[:n_fisse], strict=True):
            if nome in ("sezione", "scrutinata", "circoscrizione"):
                valori[nome] = v.strip()
            elif nome:
                valori[nome] = _intero(v)
        gruppi: list[list[str]] = []
        for v in campi[n_fisse:]:
            if v.strip() == "":
                gruppi.append([])
            elif gruppi:
                gruppi[-1].append(v)
            else:
                gruppi.append([v])
        while gruppi and not gruppi[-1]:
            gruppi.pop()
        if len(gruppi) != len(soggetti):
            raise ErroreFormato(
                f"Sezione {valori.get('sezione')}: {len(gruppi)} gruppi di voti, "
                f"attesi {len(soggetti)}"
            )
        return valori, [_intero(g[0]) if g else None for g in gruppi]

    righe_affluenza = []
    righe_voti = []
    totale: dict[str, int | None] = {}
    totale_voti: dict[int, int] = {}
    viste: set[str] = set()
    for riga in righe[i_head + 1 :]:
        if not riga.strip():
            continue
        campi = _campi(riga)
        primo = campi[0].strip()
        if primo.upper() == "TOTALE":
            valori, voti = scomponi(campi)
            totale = {k: v for k, v in valori.items() if k not in ("sezione", "circoscrizione")}
            totale_voti = {
                s.numero: v for s, v in zip(soggetti, voti, strict=True) if v is not None
            }
            continue
        # Righe di dati: iniziano con il numero di sezione e hanno tutte le colonne fisse.
        # Esclude eventuali blocchi di legenda ("1;NOME LISTA") dopo i dati.
        if not re.fullmatch(r"\d+", primo) or len(campi) <= n_fisse:
            continue
        valori, voti = scomponi(campi)
        sezione = normalizza_sezione(valori["sezione"])
        if sezione in viste:
            raise ErroreFormato(f"Sezione {sezione} ripetuta")
        viste.add(sezione)
        circ = valori.get("circoscrizione")
        righe_affluenza.append(
            {
                "sezione": sezione,
                "circoscrizione": normalizza_circoscrizione(circ) if circ else None,
                "scrutinata": valori.get("scrutinata", "S") != "N",
                **{c: valori.get(c) for c in COLONNE_AFFLUENZA[3:]},
            }
        )
        for s, v in zip(soggetti, voti, strict=True):
            righe_voti.append(
                {"sezione": sezione, "numero": s.numero, "soggetto": s.nome, "voti": v or 0}
            )

    if not righe_affluenza:
        raise ErroreFormato("Nessuna riga di sezione")
    return Riepilogo(
        titolo=titolo,
        soggetti=soggetti,
        affluenza=pd.DataFrame(righe_affluenza, columns=COLONNE_AFFLUENZA),
        voti=pd.DataFrame(righe_voti, columns=["sezione", "numero", "soggetto", "voti"]),
        lista=lista,
        scrutinate=scrutinate,
        totale=totale,
        totale_voti=totale_voti,
    )
