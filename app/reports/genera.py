"""Generazione dei report: template Jinja2 -> HTML -> PDF A4 con Playwright (Chromium headless).

I grafici sono Chart.js dentro la pagina: Playwright aspetta ``window.__renderFatto`` prima di
stampare. Le mappe sono PNG statici (app/reports/mappe.py). Se il Chromium di Playwright non è
installato si usa Microsoft Edge (``channel="msedge"``), e il registro lo annota.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.core.config import RADICE

DIR_TEMPLATE = Path(__file__).parent / "templates"
DIR_USCITA = RADICE / "reports_out"
CHART_JS = RADICE / "web" / "static" / "vendor" / "chart.umd.min.js"
TIMEOUT_MS = 30_000
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]  # fmt: skip


class ErroreReport(RuntimeError):
    pass


# --- formattazione all'italiana ----------------------------------------------


def num(v, cifre: int = 1) -> str:
    if v is None:
        return "–"
    testo = f"{v:,.{cifre}f}"
    return testo.replace(",", " ").replace(".", ",")


def segno(v, cifre: int = 1) -> str:
    if v is None:
        return "–"
    s = "+" if v > 0 else "−" if v < 0 else ""
    return s + num(abs(v), cifre)


def data_it(d) -> str:
    if d is None:
        return "–"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} {MESI[d.month - 1]} {d.year}"


def _ambiente() -> Environment:
    env = Environment(
        loader=FileSystemLoader(DIR_TEMPLATE),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(num=num, segno=segno, data_it=data_it)
    env.filters["json"] = lambda v: Markup(json.dumps(v, ensure_ascii=False).replace("</", "<\\/"))
    return env


AMBIENTE = _ambiente()


def html(tipo: str, contesto: dict) -> str:
    """HTML completo del report (usato sia per l'anteprima sia per il PDF)."""
    chart_js = CHART_JS.read_text(encoding="utf-8") if contesto.get("grafici") else ""
    return AMBIENTE.get_template(f"{tipo}.html.j2").render(**contesto, chart_js=Markup(chart_js))


# --- PDF -----------------------------------------------------------------------


@dataclass
class Pdf:
    contenuto: bytes
    pagine: int
    browser: str
    durata_s: float


def _testata(contesto: dict) -> str:
    parti = []
    if contesto.get("dati_di_prova"):
        parti.append("DATI DI PROVA")
    if contesto.get("dicitura"):
        parti.append(contesto["dicitura"])
    testo = " · ".join(parti)
    return (
        '<div style="width:100%;font-size:8px;font-family:sans-serif;text-align:center;'
        f'color:#b45309;font-weight:700;padding-top:4mm">{testo}</div>'
    )


def _piede(contesto: dict) -> str:
    titolo = str(Markup.escape(contesto.get("titolo", "")))
    extra = ""
    if contesto.get("dicitura"):
        extra = f" · <b>{Markup.escape(contesto['dicitura'])}</b>"
    return (
        '<div style="width:100%;font-size:8px;font-family:sans-serif;color:#5d6675;'
        'padding:0 14mm 3mm;display:flex;justify-content:space-between">'
        f"<span>Monitorino · {titolo}{extra}</span>"
        '<span>pagina <span class="pageNumber"></span> di <span class="totalPages"></span></span>'
        "</div>"
    )


def conta_pagine(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf))


def stampa(pagina_html: str, contesto: dict) -> Pdf:
    """Apre l'HTML in Chromium headless, aspetta i grafici e stampa in A4."""
    from playwright.sync_api import Error as ErrorePlaywright
    from playwright.sync_api import sync_playwright

    inizio = time.perf_counter()
    with sync_playwright() as p:
        browser, nome = None, ""
        for nome_b, opzioni in (("chromium", {}), ("msedge", {"channel": "msedge"})):
            try:
                browser = p.chromium.launch(**opzioni)
                nome = nome_b
                break
            except ErrorePlaywright:
                continue
        if browser is None:
            raise ErroreReport(
                "Nessun browser per la stampa: eseguire `uv run playwright install chromium`"
            )
        try:
            pagina = browser.new_page(device_scale_factor=2)
            pagina.set_default_timeout(TIMEOUT_MS)
            pagina.set_content(pagina_html, wait_until="load")
            pagina.wait_for_function("window.__renderFatto === true", timeout=TIMEOUT_MS)
            contenuto = pagina.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template=_testata(contesto),
                footer_template=_piede(contesto),
                margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
            )
        except ErrorePlaywright as e:
            raise ErroreReport(f"Stampa non riuscita: {str(e).splitlines()[0]}") from e
        finally:
            browser.close()
    return Pdf(contenuto, conta_pagine(contenuto), nome, round(time.perf_counter() - inizio, 2))


# --- archivio ------------------------------------------------------------------


def _slug(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:60] or "report"


def archivia(
    con: duckdb.DuckDBPyConnection,
    *,
    tipo: str,
    titolo: str,
    parametri: dict,
    autore: str,
    pdf: Pdf,
    cartella: Path | None = None,
) -> dict:
    cartella = cartella or DIR_USCITA
    cartella.mkdir(parents=True, exist_ok=True)
    (rid,) = con.execute(
        "INSERT INTO report (tipo, titolo, parametri, autore, pagine, durata_s, browser) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        [
            tipo,
            titolo,
            json.dumps(parametri, ensure_ascii=False),
            autore,
            pdf.pagine,
            pdf.durata_s,
            pdf.browser,
        ],  # fmt: skip
    ).fetchone()
    nome = f"{rid:04d}_{datetime.now():%Y%m%d}_{_slug(titolo)}.pdf"
    (cartella / nome).write_bytes(pdf.contenuto)
    con.execute("UPDATE report SET file = ? WHERE id = ?", [nome, rid])
    return {"id": rid, "file": nome, "pagine": pdf.pagine, "durata_s": pdf.durata_s,
            "browser": pdf.browser}  # fmt: skip
