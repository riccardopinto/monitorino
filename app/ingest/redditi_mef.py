"""Redditi IRPEF per CAP (MEF - Dipartimento delle Finanze) ripartiti su circoscrizioni e sezioni.

Fonte: MEF - Dipartimento delle Finanze, "Redditi e principali variabili IRPEF su base
subcomunale", anno d'imposta 2024 (dichiarazioni 2025).

I confini dei CAP non sono pubblicati. La ripartizione CAP -> area è pesata per popolazione:
1. ogni civico georeferenziato del Comune (2019, con CAP) cade in una sezione di censimento;
2. la popolazione ISTAT 2021 di ogni sezione di censimento si divide tra i CAP dei suoi
   civici, in proporzione al numero di civici (sezioni senza civici: CAP del civico più vicino);
3. si ottiene la popolazione per (CAP, area) e da questa la quota di ogni CAP in ogni area.
Il risultato per area è una stima; il totale cittadino (area 0) è la somma esatta dei CAP.

Uso: ``uv run python -m app.ingest.redditi_mef`` (dopo censimento_istat e sezioni).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd

from app.core import db
from app.core.config import impostazioni
from app.ingest import censimento_istat as ci
from app.ingest import sezioni as sez
from app.ingest._comune import registra_caricamento, scarica
from app.ingest.elezioni.riepilogo import decodifica

FONTE = "mef_redditi"
ETICHETTA = "MEF - Dipartimento delle Finanze"
ANNO = 2024
URL = (
    "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/"
    "Redditi_e_principali_variabili_IRPEF_su_base_subcomunale_CSV_2024.zip"
)
COLONNE = {
    "Numero contribuenti": "mef_contribuenti",
    "Reddito complessivo - Frequenza": "mef_reddito_complessivo_n",
    "Reddito complessivo - Ammontare in euro": "mef_reddito_complessivo_eur",
    "Reddito imponibile - Ammontare in euro": "mef_reddito_imponibile_eur",
    "Imposta netta - Ammontare in euro": "mef_imposta_netta_eur",
    "Reddito da lavoro dipendente e assimilati - Ammontare in euro": "mef_lavoro_dipendente_eur",
    "Reddito da pensione - Ammontare in euro": "mef_pensione_eur",
}


class ErroreIngest(RuntimeError):
    pass


def leggi_redditi(percorso: Path) -> pd.DataFrame:
    with zipfile.ZipFile(percorso) as zf:
        nome = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        testo = decodifica(zf.read(nome))
    d = pd.read_csv(io.StringIO(testo), sep=";", dtype=str)
    d.columns = [c.strip() for c in d.columns]
    d = d[d["Codice Istat Comune"].str.strip() == "001272"]
    if d.empty:
        raise ErroreIngest("Nessuna riga di Torino nel file MEF")
    mancanti = set(COLONNE) - set(d.columns)
    if mancanti:
        raise ErroreIngest(f"Colonne mancanti nel file MEF: {sorted(mancanti)}")
    out = d[["CAP", *COLONNE]].rename(columns=COLONNE)
    for c in COLONNE.values():
        out[c] = pd.to_numeric(out[c]).fillna(0)
    out["CAP"] = out["CAP"].str.strip()
    return out.set_index("CAP")


def popolazione_per_cap(
    civici: pd.DataFrame, geometrie: gpd.GeoDataFrame, popolazione: pd.Series
) -> pd.DataFrame:
    """Popolazione per (sezione di censimento, CAP).

    ``civici``: colonne cap, lon, lat. ``geometrie``: SEZ21_ID e geometrie delle sezioni di
    censimento. ``popolazione``: residenti per SEZ21_ID. Restituisce SEZ21_ID, CAP, pop.
    """
    punti = gpd.GeoDataFrame(
        civici[["cap"]], geometry=gpd.points_from_xy(civici["lon"], civici["lat"]), crs=4326
    ).to_crs(geometrie.crs)
    unite = gpd.sjoin(punti, geometrie[["SEZ21_ID", "geometry"]], predicate="within")
    conteggi = unite.groupby(["SEZ21_ID", "cap"]).size().rename("n").reset_index()

    abitate = popolazione[popolazione > 0].index
    senza = sorted(set(abitate) - set(conteggi["SEZ21_ID"]))
    if senza:
        # Sezioni abitate senza civici al loro interno: CAP del civico più vicino.
        centri = geometrie[geometrie["SEZ21_ID"].isin(senza)].copy()
        centri["geometry"] = centri.geometry.representative_point()
        vicini = gpd.sjoin_nearest(centri[["SEZ21_ID", "geometry"]], punti)
        vicini = vicini[~vicini["SEZ21_ID"].duplicated()]
        conteggi = pd.concat([conteggi, vicini[["SEZ21_ID", "cap"]].assign(n=1)], ignore_index=True)

    conteggi["quota"] = conteggi["n"] / conteggi.groupby("SEZ21_ID")["n"].transform("sum")
    conteggi["pop"] = conteggi["quota"] * conteggi["SEZ21_ID"].map(popolazione).fillna(0)
    return conteggi[["SEZ21_ID", "cap", "pop"]]


def ripartisci(redditi: pd.DataFrame, pop_cap: pd.DataFrame, area_di: pd.Series) -> pd.DataFrame:
    """Ripartisce le variabili di ogni CAP sulle aree, in proporzione alla popolazione.

    ``area_di``: area (codice) di ogni SEZ21_ID. Restituisce area, variabile, valore.
    """
    p = pop_cap.assign(area=pop_cap["SEZ21_ID"].map(area_di)).dropna(subset=["area"])
    per = p.groupby(["cap", "area"])["pop"].sum().reset_index()
    per["quota"] = per["pop"] / per.groupby("cap")["pop"].transform("sum")
    senza_pop = sorted(set(redditi.index) - set(per["cap"]))
    if senza_pop:
        raise ErroreIngest(f"CAP del file MEF senza popolazione nelle aree: {senza_pop}")
    lungo = redditi.reset_index().melt(id_vars="CAP", var_name="variabile", value_name="valore")
    unito = lungo.merge(per, left_on="CAP", right_on="cap")
    unito["valore"] = unito["valore"] * unito["quota"]
    return unito.groupby(["area", "variabile"])["valore"].sum().reset_index()


def scrivi(
    con: duckdb.DuckDBPyConnection,
    per_circ: pd.DataFrame,
    per_sezione: pd.DataFrame,
    totali: pd.Series,
) -> int:
    circ_ids = dict(
        con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall()
    )
    sez_ids = dict(con.execute("SELECT codice, id FROM area WHERE tipo = 'sezione'").fetchall())
    righe = pd.concat(
        [
            per_circ.assign(area_id=per_circ["area"].map(circ_ids)),
            per_sezione.assign(area_id=per_sezione["area"].map(sez_ids)),
            pd.DataFrame(
                {"area_id": ci.AREA_COMUNE, "variabile": totali.index, "valore": totali.values}
            ),
        ]
    ).dropna(subset=["area_id"])
    righe = righe.assign(anno=ANNO, fonte=ETICHETTA)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM demografia WHERE fonte = ?", [ETICHETTA])
        con.register("_mef", righe)
        con.execute(
            "INSERT INTO demografia (area_id, anno, variabile, valore, fonte) "
            "SELECT CAST(area_id AS INTEGER), anno, variabile, valore, fonte FROM _mef"
        )
        con.unregister("_mef")
        registra_caricamento(con, FONTE, len(righe))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(righe)


def main() -> None:
    redditi = leggi_redditi(scarica(URL, FONTE))
    # Civici georeferenziati del Comune (stessa fonte della Fase 1): qui serve il CAP.
    grezzi = pd.read_csv(scarica(sez.URL_CIVICI, sez.FONTE_CIVICI), dtype=str)
    civici = pd.DataFrame(
        {
            "cap": grezzi["CAP"].str.strip(),
            "lon": grezzi["COORDINATA_X"].str.replace(",", ".").astype(float),
            "lat": grezzi["COORDINATA_Y"].str.replace(",", ".").astype(float),
        }
    ).dropna()
    sezioni = ci.leggi_sezioni(scarica(ci.URL_DATI, ci.FONTE))
    geometrie = ci.leggi_geometrie(scarica(ci.URL_BASI, ci.FONTE))
    popolazione = sezioni.set_index("SEZ21_ID")["cens_pop"]
    pop_cap = popolazione_per_cap(civici, geometrie, popolazione)

    elettorale = pd.read_csv(
        ci.DIR_PROCESSED / "censimento_sezioni_elettorali.csv", dtype={"sezione": str}
    ).set_index("SEZ21_ID")["sezione"]
    per_circ = ripartisci(redditi, pop_cap, sezioni.set_index("SEZ21_ID")["circoscrizione"])
    per_sez = ripartisci(redditi, pop_cap, elettorale)

    totali = redditi.sum()
    controllo = per_circ.groupby("variabile")["valore"].sum()
    scarto = ((controllo - totali).abs() / totali).max()
    if scarto > 1e-9:
        raise ErroreIngest(f"La ripartizione non conserva i totali (scarto {scarto:.2e})")

    with db.connetti(impostazioni().db_path) as con:
        db.crea_schema(con)
        n = scrivi(con, per_circ, per_sez, totali)
    medio = totali["mef_reddito_complessivo_eur"] / totali["mef_reddito_complessivo_n"]
    print(
        f"Righe scritte: {n}. Contribuenti: {int(totali['mef_contribuenti']):,}".replace(",", ".")
    )
    print(f"Reddito complessivo medio a Torino: {medio:,.0f} euro".replace(",", "."))
    c = per_circ.pivot(index="area", columns="variabile", values="valore")
    medi = c["mef_reddito_complessivo_eur"] / c["mef_reddito_complessivo_n"]
    for area, v in medi.sort_index().items():
        print(f"  circoscrizione {area}: {v:,.0f} euro (stima)".replace(",", "."))


if __name__ == "__main__":
    main()
