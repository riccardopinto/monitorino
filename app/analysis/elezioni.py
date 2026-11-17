"""Analisi dei risultati elettorali: aggregazioni per area, variazioni, flussi stimati.

Livelli territoriali:
- "sezione": il codice della sezione elettorale;
- "circoscrizione": dalla corrispondenza sezione -> circoscrizione dell'anno dell'elezione;
- "citta": un'unica area, codice "Torino".

Raggruppamenti dei voti ("tipo"):
- "lista": le liste così come si chiamano nei file;
- "forza": forza politica normalizzata (config/aree_politiche.yaml), confrontabile tra elezioni;
- "area": area politica (centrosinistra, centrodestra, M5S, civici e terzo polo, altro);
- "candidato": candidati sindaco, presidente o uninominali.
Per forza e area si usano le liste; se l'elezione non ha liste (ballottaggio) i candidati.

Inferenza ecologica: questi dati descrivono sezioni e aree, non persone. Le stime di flusso
sono ottenute con una regressione su dati aggregati e non dicono come ha votato nessun
elettore in particolare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize

Livello = Literal["sezione", "circoscrizione", "citta"]
Tipo = Literal["lista", "forza", "area", "candidato"]

TIPI_CANDIDATO = ("candidato_sindaco", "candidato_presidente", "candidato_uninominale")
NON_VOTO = "non voto"
ETICHETTA_STIMA = (
    "Stima statistica (regressione ecologica): non descrive il comportamento dei singoli elettori"
)


def _codice_area(livello: Livello) -> str:
    return {
        "sezione": "r.sezione",
        "circoscrizione": "sa.circoscrizione",
        "citta": "'Torino'",
    }[livello]


def ha_liste(con: duckdb.DuckDBPyConnection, eid: int) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM risultato WHERE elezione_id = ? AND tipo_soggetto = 'lista'",
            [eid],
        ).fetchone()[0]
    )


def _base_voti(con: duckdb.DuckDBPyConnection, eid: int, tipo: Tipo) -> tuple[str, str]:
    """Filtro sui tipi di soggetto e espressione del soggetto raggruppato."""
    candidati = "(" + ", ".join(f"'{t}'" for t in TIPI_CANDIDATO) + ")"
    if tipo == "lista":
        return "r.tipo_soggetto = 'lista'", "r.soggetto"
    if tipo == "candidato":
        return f"r.tipo_soggetto IN {candidati}", "r.soggetto"
    colonna = "a.forza_politica" if tipo == "forza" else "a.area_politica"
    if ha_liste(con, eid):
        return "r.tipo_soggetto = 'lista'", colonna
    return f"r.tipo_soggetto IN {candidati}", colonna


def risultati(
    con: duckdb.DuckDBPyConnection, eid: int, livello: Livello = "citta", tipo: Tipo = "lista"
) -> pd.DataFrame:
    """Voti e quote per area e soggetto: colonne area, soggetto, voti, quota (0-1)."""
    filtro, soggetto = _base_voti(con, eid, tipo)
    area = _codice_area(livello)
    return con.execute(
        f"""
        WITH v AS (
            SELECT {area} AS area, {soggetto} AS soggetto, sum(r.voti) AS voti
            FROM risultato r
            JOIN elezione e ON e.id = r.elezione_id
            LEFT JOIN sezione_area sa ON sa.sezione = r.sezione AND sa.anno = year(e.data)
            LEFT JOIN lista_alias a ON a.elezione_id = r.elezione_id AND a.soggetto = r.soggetto
                AND a.tipo = CASE WHEN r.tipo_soggetto = 'lista' THEN 'lista' ELSE 'candidato' END
            WHERE r.elezione_id = ? AND {filtro}
            GROUP BY ALL
        )
        SELECT area, soggetto, voti::BIGINT AS voti,
               voti / nullif(sum(voti) OVER (PARTITION BY area), 0) AS quota
        FROM v ORDER BY area, voti DESC
        """,
        [eid],
    ).df()


def affluenza(con: duckdb.DuckDBPyConnection, eid: int, livello: Livello = "citta") -> pd.DataFrame:
    """Colonne area, elettori, votanti, affluenza (0-1)."""
    area = _codice_area(livello).replace("r.", "f.")
    return con.execute(
        f"""
        SELECT {area} AS area, sum(f.elettori)::BIGINT AS elettori,
               sum(f.votanti)::BIGINT AS votanti,
               sum(f.votanti) / nullif(sum(f.elettori), 0) AS affluenza
        FROM affluenza f
        JOIN elezione e ON e.id = f.elezione_id
        LEFT JOIN sezione_area sa ON sa.sezione = f.sezione AND sa.anno = year(e.data)
        WHERE f.elezione_id = ?
        GROUP BY ALL ORDER BY area
        """,
        [eid],
    ).df()


def variazione(
    con: duckdb.DuckDBPyConnection,
    eid_da: int,
    eid_a: int,
    livello: Livello = "circoscrizione",
    tipo: Tipo = "area",
) -> pd.DataFrame:
    """Differenza di quota tra due elezioni, in punti percentuali.

    Colonne area, soggetto, quota_da, quota_a, variazione_punti. A livello di sezione si usano
    solo le sezioni presenti in entrambe le elezioni.
    """
    da = risultati(con, eid_da, livello, tipo)
    a = risultati(con, eid_a, livello, tipo)
    aree_comuni = set(da["area"]) & set(a["area"])
    unite = da.merge(a, on=["area", "soggetto"], how="outer", suffixes=("_da", "_a"))
    unite = unite[unite["area"].isin(aree_comuni)]
    unite[["quota_da", "quota_a"]] = unite[["quota_da", "quota_a"]].fillna(0.0)
    unite["variazione_punti"] = (unite["quota_a"] - unite["quota_da"]) * 100
    return unite[["area", "soggetto", "quota_da", "quota_a", "variazione_punti"]].reset_index(
        drop=True
    )


# --- flussi -----------------------------------------------------------------


@dataclass
class Flussi:
    categorie_da: list[str]
    categorie_a: list[str]
    matrice: pd.DataFrame  # righe: da, colonne: a; quota di ogni categoria di partenza (0-1)
    elettori: pd.DataFrame  # stessa forma: elettori stimati che passano da riga a colonna
    r2: dict[str, float]  # bontà dell'adattamento per ogni categoria di arrivo
    n_sezioni: int
    etichetta: str = ETICHETTA_STIMA


def quote_elettori(con: duckdb.DuckDBPyConnection, eid: int) -> pd.DataFrame:
    """Per sezione: elettori e voti per area politica, più il non voto (righe: sezioni)."""
    voti = risultati(con, eid, "sezione", "area").pivot_table(
        index="area", columns="soggetto", values="voti", aggfunc="sum", fill_value=0
    )
    aff = affluenza(con, eid, "sezione").set_index("area")
    tab = voti.join(aff[["elettori"]], how="inner")
    tab = tab[tab["elettori"] > 0]  # sezioni ospedaliere: votanti senza elettori iscritti
    tab[NON_VOTO] = (tab["elettori"] - tab.drop(columns="elettori").sum(axis=1)).clip(lower=0)
    return tab


def stima_flussi(x: np.ndarray, y: np.ndarray, pesi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Regressione ecologica di Goodman con vincoli.

    ``x`` (n x k) e ``y`` (n x m) sono quote sugli elettori, righe che sommano a 1.
    Trova B (k x m) con valori in [0, 1] e righe che sommano a 1 che minimizza
    sum_i peso_i * ||y_i - x_i B||^2. Restituisce B e l'R² pesato di ogni colonna.
    """
    k, m = x.shape[1], y.shape[1]
    w = pesi / pesi.sum()

    def obiettivo(b: np.ndarray) -> float:
        residui = y - x @ b.reshape(k, m)
        return float((w[:, None] * residui**2).sum())

    def gradiente(b: np.ndarray) -> np.ndarray:
        residui = y - x @ b.reshape(k, m)
        return (-2 * x.T @ (w[:, None] * residui)).ravel()

    vincoli = [
        {"type": "eq", "fun": (lambda b, i=i: b.reshape(k, m)[i].sum() - 1.0)} for i in range(k)
    ]
    iniziale = np.full(k * m, 1.0 / m)
    esito = minimize(
        obiettivo,
        iniziale,
        jac=gradiente,
        bounds=[(0.0, 1.0)] * (k * m),
        constraints=vincoli,
        method="SLSQP",
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    b = np.clip(esito.x.reshape(k, m), 0, 1)
    b = b / b.sum(axis=1, keepdims=True)
    previsti = x @ b
    medie = (w[:, None] * y).sum(axis=0)
    ss_res = (w[:, None] * (y - previsti) ** 2).sum(axis=0)
    ss_tot = (w[:, None] * (y - medie) ** 2).sum(axis=0)
    r2 = np.where(ss_tot > 0, 1 - ss_res / np.where(ss_tot > 0, ss_tot, 1), np.nan)
    return b, r2


def flussi(
    con: duckdb.DuckDBPyConnection,
    eid_da: int,
    eid_a: int,
    circoscrizione: str | None = None,
    soglia_variazione_elettori: float = 0.10,
) -> Flussi:
    """Flussi stimati tra aree politiche (e non voto) di due elezioni.

    Si usano le sezioni presenti in entrambe le elezioni con elettori simili (variazione
    sotto la soglia), eventualmente solo quelle di una circoscrizione.
    """
    da = quote_elettori(con, eid_da)
    a = quote_elettori(con, eid_a)
    comuni = da.index.intersection(a.index)
    da, a = da.loc[comuni], a.loc[comuni]
    variazione_el = (a["elettori"] - da["elettori"]).abs() / da["elettori"]
    tenere = variazione_el < soglia_variazione_elettori
    if circoscrizione is not None:
        anno_a = con.execute("SELECT year(data) FROM elezione WHERE id = ?", [eid_a]).fetchone()[0]
        nella_circ = {
            r[0]
            for r in con.execute(
                "SELECT sezione FROM sezione_area WHERE anno = ? AND circoscrizione = ?",
                [anno_a, circoscrizione],
            ).fetchall()
        }
        tenere &= da.index.isin(nella_circ)
    da, a = da[tenere], a[tenere]
    if len(da) < 20:
        raise ValueError(f"Troppe poche sezioni confrontabili ({len(da)}) per stimare i flussi")

    cat_da = [c for c in da.columns if c != "elettori"]
    cat_a = [c for c in a.columns if c != "elettori"]
    x = da[cat_da].to_numpy(float) / da["elettori"].to_numpy(float)[:, None]
    y = a[cat_a].to_numpy(float) / a["elettori"].to_numpy(float)[:, None]
    # Le quote sommano a 1 a meno di arrotondamenti (non voto tagliato a zero).
    x = x / x.sum(axis=1, keepdims=True)
    y = y / y.sum(axis=1, keepdims=True)
    pesi = da["elettori"].to_numpy(float)
    b, r2 = stima_flussi(x, y, pesi)

    matrice = pd.DataFrame(b, index=cat_da, columns=cat_a)
    totali_da = (x * pesi[:, None]).sum(axis=0)
    elettori = matrice.mul(totali_da, axis=0).round().astype(int)
    return Flussi(
        categorie_da=cat_da,
        categorie_a=cat_a,
        matrice=matrice,
        elettori=elettori,
        r2=dict(zip(cat_a, (float(v) for v in r2), strict=True)),
        n_sezioni=len(da),
    )
