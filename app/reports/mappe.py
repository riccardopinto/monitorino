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


def classi(valori: list[float], divergente: bool) -> tuple[list[float], list[str]]:
    """Limiti e colori, come Scala.classi in scale.js."""
    numeri = [v for v in valori if v is not None]
    if not numeri:
        return [], []
    if divergente:
        m = max(abs(v) for v in numeri) or 1
        passo = m / 3.5
        return [k * passo for k in (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)], DIVERGENTE
    lo, hi = min(numeri), max(numeri)
    n = len(SEQUENZIALE)
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
        scuro = fondo is not None and fondo in SEQUENZIALE[PRIMO_SCURO:]
        ax.annotate(r.codice, (p.x, p.y), ha="center", va="center", fontsize=9, weight="bold",
                    color="white" if scuro else "#1d2330")  # fmt: skip


def coropletica(
    con: duckdb.DuckDBPyConnection,
    valori: dict[str, float | None],
    *,
    divergente: bool = False,
    formato: Callable[[float], str] = lambda v: f"{v:.1f}",
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
    for i, c in enumerate(colori):
        da = limiti[i - 1] if i > 0 else None
        a = limiti[i] if i < len(limiti) else None
        testo = (f"meno di {formato(a)}" if da is None else
                 f"da {formato(da)}" if a is None else f"{formato(da)} – {formato(a)}")  # fmt: skip
        voci.append(Patch(facecolor=c, edgecolor=BORDO, linewidth=0.4, label=testo))
    if NESSUN_DATO in fondo.values():
        voci.append(
            Patch(facecolor=NESSUN_DATO, edgecolor=BORDO, linewidth=0.4, label="nessun dato")
        )
    if voci:
        ax.legend(handles=voci, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8,
                  frameon=False)  # fmt: skip
    return _png(fig)


def evidenzia(con: duckdb.DuckDBPyConnection, codice: str) -> str:
    """Torino con la circoscrizione indicata in evidenza."""
    gdf = circoscrizioni(con)
    fig, ax = plt.subplots(figsize=(4.2, 4.0))
    colori = [EVIDENZA if c == codice else "#eeeeec" for c in gdf.codice]
    gdf.plot(ax=ax, color=colori, edgecolor=BORDO, linewidth=0.8)
    _etichette(ax, gdf)
    ax.set_axis_off()
    return _png(fig)
