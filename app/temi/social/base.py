"""Interfaccia comune dei connettori social e salvataggio dei contenuti.

Regole (CLAUDE.md, vincoli di privacy):
- solo contenuti pubblici, raccolti con API ufficiali e credenziali dello staff;
- al momento della raccolta si scartano autore, ID e link: il connettore restituisce solo
  testo e data, e dal testo si tolgono menzioni, URL ed email;
- il testo si salva con una scadenza (conservazione_testi_giorni) e un job lo cancella;
- in documento, per i social, url è sempre NULL e l'impronta è l'hash del testo.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import duckdb
import httpx

from app.temi.news import impronta

USER_AGENT = "monitorino/0.1 (analisi aggregata di contenuti pubblici)"

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_MENZIONE = re.compile(r"(?<![\w])@[\w.\-]+")
_UTENTE_REDDIT = re.compile(r"(?<![\w])/?u/[\w\-]+", re.IGNORECASE)


def anonimizza(testo: str) -> str:
    """Toglie URL, email, menzioni (@nome) e riferimenti a utenti Reddit (u/nome)."""
    t = _URL.sub(" ", testo)
    t = _EMAIL.sub(" ", t)
    t = _MENZIONE.sub(" ", t)
    t = _UTENTE_REDDIT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass(frozen=True)
class ContenutoPubblico:
    """Quello che resta di un contenuto social dopo la raccolta: testo e data, nient'altro."""

    testo: str
    data: date


class ErroreConnettore(RuntimeError):
    pass


class Connettore(ABC):
    nome: str  # come compare in documento.fonte, es. "Reddit r/torino"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})

    @abstractmethod
    def raccogli(self, dal: datetime) -> list[ContenutoPubblico]:
        """Contenuti pubblicati dopo ``dal``, già anonimizzati."""

    @staticmethod
    def contenuto(testo: str | None, quando: datetime) -> ContenutoPubblico | None:
        pulito = anonimizza(testo or "")
        if len(pulito) < 20:  # frasi troppo corte non dicono nulla sul tema
            return None
        return ContenutoPubblico(pulito, quando.date())


def scrivi(
    con: duckdb.DuckDBPyConnection, fonte: str, contenuti: list[ContenutoPubblico], giorni: int
) -> int:
    scadenza = date.today() + timedelta(days=giorni)
    nuovi = 0
    for c in contenuti:
        imp = impronta(fonte, c.testo)
        if con.execute("SELECT count(*) FROM documento WHERE impronta = ?", [imp]).fetchone()[0]:
            continue
        con.execute(
            "INSERT INTO documento (fonte, tipo_fonte, url, data, testo, impronta, scadenza) "
            "VALUES (?, 'social', NULL, ?, ?, ?, ?)",
            [fonte, c.data, c.testo, imp, scadenza],
        )
        nuovi += 1
    return nuovi
