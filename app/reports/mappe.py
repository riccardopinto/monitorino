"""Mappe statiche per i report (PNG generati lato server, sempre uguali a parità di dati).

Stesse scale della dashboard (web/static/js/scale.js): viridis per le quantità, rosso-grigio-blu
per variazioni e saldi. Niente tile di sfondo: il PDF non fa richieste esterne.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable

import duckdb
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import shapely  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SEQUENZIALE = ["#fde725", "#7ad151", "#22a884", "#2a788e", "#414487", "#440154"]
DIVERGENTE = ["#b2182b", "#ef8a62", "#fddbc7", "#ededed", "#d1e5f0", "#67a9cf", "#2166ac"]
PRIMO_SCURO = 3
NESSUN_DATO = "#d9d9d6"
# Colori su cui le etichette vanno in bianco.
SCURI = {*SEQUENZIALE[PRIMO_SCURO:], DIVERGENTE[0], DIVERGENTE[-1]}
BORDO = "#4a4f57"
EVIDENZA = "#e66100"


def circoscrizioni(con: duckdb.DuckDBPyConnection) -> gpd.GeoDataFrame:
    righe = con.execute(
        "SELECT codice, nome, ST_AsWKB(geometria) FROM area "
        "WHERE tipo = 'circoscrizione' AND geometria IS NOT NULL ORDER BY codice"
    ).fetchall()
    if not righe:
        raise ValueError("Nessuna geometria delle circoscrizioni nel database")
    geometrie = [shapely.from_wkb(bytes(g)) for _, _, g in righe]
    return gpd.GeoDataFrame(
        {"codice": [r[0] for r in righe], "nome": [r[1] for r in righe]},
        geometry=geometrie,
        crs="EPSG:4326",
    ).to_crs("EPSG:32632")


def valori_interi(numeri: list[float]) -> list[int] | None:
    """Valori interi distinti se sono conteggi con pochi valori: una classe per valore."""
    if not numeri or any(float(v) != int(v) for v in numeri):
        return None
    lo, hi = int(min(numeri)), int(max(numeri))
    return list(range(lo, hi + 1)) if hi - lo < len(SEQUENZIALE) else None


def classi(valori: list[float], divergente: bool) -> tuple[list[float], list[str]]:
    """Limiti e colori, come Scala.classi in scale.js.

    - Divergente con valori di segno misto: scala simmetrica intorno allo zero.
    - Divergente con valori tutti dello stesso segno: solo il ramo di quel segno, con classi
      tra minimo e massimo (altrimenti finirebbero tutti nella stessa classe).
    - Sequenziale: intervalli uguali; per conteggi con pochi valori, una classe per valore.
    """
    numeri = [v for v in valori if v is not None]
    if not numeri:
        return [], []
    lo, hi = min(numeri), max(numeri)
    if divergente:
        if lo >= 0 < hi or hi <= 0 > lo:
            ramo = DIVERGENTE[4:] if lo >= 0 else DIVERGENTE[:3]
            passo = (hi - lo) / 3 or 1
            return [lo + passo, lo + 2 * passo], ramo
        m = max(abs(v) for v in numeri) or 1
        passo = m / 3.5
        return [k * passo for k in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)], DIVERGENTE
    n = len(SEQUENZIALE)
    interi = valori_interi(numeri)
    if interi:
        k = len(interi)
        colori = (
            [SEQUENZIALE[round(i * (n - 1) / (k - 1))] for i in range(k)]
            if k > 1
            else [SEQUENZIALE[2]]
        )
        return [float(v) for v in interi[1:]], colori
    passo = (hi - lo) / n or 1
    return [lo + passo * (i + 1) for i in range(n - 1)], SEQUENZIALE


def colore_di(limiti: list[float], colori: list[str], v: float) -> str:
    i = 0
    while i < len(limiti) and v >= limiti[i]:
        i += 1
    return colori[i]


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _etichette(ax, gdf: gpd.GeoDataFrame, colori_fondo: dict[str, str] | None = None) -> None:
    for _, r in gdf.iterrows():
        p = r.geometry.representative_point()
        fondo = (colori_fondo or {}).get(r.codice)
        scuro = fondo in SCURI
        ax.annotate(r.codice, (p.x, p.y), ha="center", va="center", fontsize=9, weight="bold",
                    color="white" if scuro else "#1d2330")  # fmt: skip


def _etichetta_classe(formato: Callable[[float], str], da, a) -> str:
    if da is None:
        return f"meno di {formato(a)}"
    if a is None:
        return f"da {formato(da)}"
    return f"{formato(da)} – {formato(a)}"


def coropletica(
    con: duckdb.DuckDBPyConnection,
    valori: dict[str, float | None],
    *,
    divergente: bool = False,
    formato: Callable[[float], str] = lambda v: f"{v:.1f}".replace(".", ","),
    titolo: str = "",
) -> str:
    """Circoscrizioni colorate per valore; restituisce un data URI PNG."""
    gdf = circoscrizioni(con)
    limiti, colori = classi(list(valori.values()), divergente)
    fondo = {}
    for codice in gdf.codice:
        v = valori.get(codice)
        fondo[codice] = NESSUN_DATO if v is None or not colori else colore_di(limiti, colori, v)
    fig, ax = plt.subplots(figsize=(6.2, 5.6))
    gdf.plot(ax=ax, color=[fondo[c] for c in gdf.codice], edgecolor=BORDO, linewidth=0.8)
    _etichette(ax, gdf, fondo)
    ax.set_axis_off()
    if titolo:
        ax.set_title(titolo, fontsize=10, loc="left")
    voci = []
    interi = None if divergente else valori_interi([v for v in valori.values() if v is not None])
    for i, c in enumerate(colori):
        da = limiti[i - 1] if i > 0 else None
        a = limiti[i] if i < len(limiti) else None
        testo = formato(interi[i]) if interi else _etichetta_classe(formato, da, a)
        voci.append(Patch(facecolor=c, edgecolor=BORDO, linewidth=0.4, label=testo))
    if NESSUN_DATO in fondo.values():
        voci.append(
            Patch(facecolor=NESSUN_DATO, edgecolor=BORDO, linewidth=0.4, label="nessun dato")
        )
    if voci:
        ax.legend(handles=voci, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8,
                  frameon=False)  # fmt: skip
    return _png(fig)


def evidenzia(con: duckdb.DuckDBPyConnection, codici: str | dict[str, str]) -> str:
    """Torino con una o più circoscrizioni in evidenza ({codice: colore} per più aree)."""
    colori_aree = {codici: EVIDENZA} if isinstance(codici, str) else codici
    gdf = circoscrizioni(con)
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    colori = [colori_aree.get(c, "#eeeeec") for c in gdf.codice]
    gdf.plot(ax=ax, color=colori, edgecolor=BORDO, linewidth=0.8)
    _etichette(ax, gdf)
    ax.set_axis_off()
    return _png(fig)
