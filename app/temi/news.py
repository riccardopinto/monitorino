"""Raccolta delle news locali dai feed RSS di config/fonti.yaml.

Si salvano titolo, link, data, testata e una sintesi breve: il sommario del feed senza
HTML, al massimo 300 caratteri. Il testo integrale degli articoli non si scarica.
L'XML originale di ogni feed va in data/raw/news/<data>/.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import date, datetime

import duckdb
import feedparser

from app.core.config import fonti
from app.ingest._comune import registra_caricamento, scarica
from app.ingest.demografia_comune import slug

FONTE_RAW = "news"
SINTESI_MAX = 300
GIORNI_MAX = 30  # articoli più vecchi si scartano: un feed fermo si nota dagli esiti


@dataclass(frozen=True)
class Articolo:
    fonte: str
    tipo_fonte: str  # news | istituzionale
    url: str
    data: date
    titolo: str
    sintesi: str

    @property
    def impronta(self) -> str:
        return impronta(self.fonte, self.titolo, self.data.isoformat())


def impronta(*parti: str) -> str:
    return hashlib.sha256("\x1f".join(parti).encode("utf-8")).hexdigest()[:32]


def testo_semplice(valore: str | None) -> str:
    """Toglie tag HTML ed entità, comprime gli spazi."""
    if not valore:
        return ""
    senza_tag = re.sub(r"<[^>]+>", " ", valore)
    return re.sub(r"\s+", " ", html.unescape(senza_tag)).strip()


def accorcia(testo: str, massimo: int = SINTESI_MAX) -> str:
    if len(testo) <= massimo:
        return testo
    taglio = testo[: massimo - 1].rsplit(" ", 1)[0]
    return taglio.rstrip(" ,;:.") + "…"


def _data(voce) -> date:
    for campo in ("published_parsed", "updated_parsed"):
        t = voce.get(campo)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return date.today()


def leggi_feed(dati: bytes, fonte: str, tipo_fonte: str) -> list[Articolo]:
    feed = feedparser.parse(dati)
    if feed.bozo and not feed.entries:
        raise ValueError(f"{fonte}: feed non leggibile ({feed.get('bozo_exception')})")
    out = []
    for voce in feed.entries:
        url = (voce.get("link") or "").strip()
        titolo = testo_semplice(voce.get("title"))
        if not url or not titolo:
            continue
        sommario = testo_semplice(voce.get("summary") or voce.get("description"))
        # Alcuni feed ripetono il titolo come sommario: in quel caso non serve.
        if sommario.lower() == titolo.lower():
            sommario = ""
        out.append(Articolo(fonte, tipo_fonte, url, _data(voce), titolo, accorcia(sommario)))
    return out


def scrivi(con: duckdb.DuckDBPyConnection, articoli: list[Articolo]) -> int:
    """Inserisce gli articoli nuovi (per URL e impronta). Restituisce quanti ne ha aggiunti."""
    nuovi = 0
    for a in articoli:
        gia = con.execute(
            "SELECT count(*) FROM documento WHERE url = ? OR impronta = ?", [a.url, a.impronta]
        ).fetchone()[0]
        if gia:
            continue
        con.execute(
            "INSERT INTO documento (fonte, tipo_fonte, url, data, titolo, sintesi, impronta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [a.fonte, a.tipo_fonte, a.url, a.data, a.titolo, a.sintesi or None, a.impronta],
        )
        nuovi += 1
    return nuovi


def raccogli(con: duckdb.DuckDBPyConnection, scaricatore=scarica) -> dict[str, str]:
    """Legge tutti i feed attivi. Un feed che non risponde non ferma gli altri."""
    cfg = fonti()
    esiti: dict[str, str] = {}
    totale = 0
    elenco = [(f, "news") for f in cfg.news] + [(f, "istituzionale") for f in cfg.istituzionali]
    for f, tipo in elenco:
        if not f.attiva or not f.rss.startswith("http"):
            continue
        try:
            percorso = scaricatore(
                f.rss, FONTE_RAW, nome_file=f"{slug(f.nome)}_{datetime.now():%H%M}.xml"
            )
            articoli = leggi_feed(percorso.read_bytes(), f.nome, tipo)
            limite = date.today().toordinal() - GIORNI_MAX
            recenti = [a for a in articoli if a.data.toordinal() >= limite]
            n = scrivi(con, recenti)
            totale += n
            esiti[f.nome] = f"{len(articoli)} nel feed, {n} nuovi"
            if articoli and not recenti:
                esiti[f.nome] += f" (ATTENZIONE: nessun articolo degli ultimi {GIORNI_MAX} giorni)"
        except Exception as e:  # noqa: BLE001 - si registra e si passa alla fonte successiva
            esiti[f.nome] = f"ERRORE: {e}"
    registra_caricamento(con, FONTE_RAW, totale)
    return esiti
