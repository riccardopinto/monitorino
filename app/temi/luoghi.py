"""Dizionario dei luoghi di Torino e assegnazione dei documenti a una circoscrizione.

Fonti (Comune di Torino, CC BY 4.0):
- vie: numerazione civica 2019 (via + circoscrizione di ogni civico). Una via entra nel
  dizionario solo se almeno l'80% dei suoi civici sta in una circoscrizione;
- quartieri: nomi ufficiali delle circoscrizioni (geoportale) e config/segmenti.yaml;
- mercati, impianti sportivi, biblioteche, scuole: geoportale, con la circoscrizione.

Per le vie si usano il nome completo ("via pietro palmieri") e la forma breve tipo + ultima
parola ("via palmieri"); le forme che portano a circoscrizioni diverse si scartano.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

import duckdb
import geopandas as gpd
import pandas as pd

from app.core.codici import normalizza_circoscrizione
from app.core.config import segmenti
from app.ingest import sezioni as sez
from app.ingest._comune import scarica

GEOPORTALE = "http://geoportale.comune.torino.it/geodati/zip/{}_geo.zip"
FONTE_RAW = "geoportale_luoghi"
SOGLIA_VIA = 0.8
TIPI_VIA = {
    "via", "corso", "piazza", "piazzale", "piazzetta", "largo", "viale", "strada", "lungo",
    "lungodora", "lungopo", "vicolo", "galleria", "passaggio", "rotonda", "borgata", "salita",
    "stradale", "lungo dora", "lungo po", "giardino", "parco",
}  # fmt: skip
# Nomi di quartiere troppo comuni da soli: si riconoscono solo con "quartiere"/"borgo" davanti.
QUARTIERI_AMBIGUI = {"centro", "barca", "sassi", "aurora", "parella", "lucento"}
MAX_PAROLE = 7


def normalizza(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("'", " ").replace("’", " ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


@dataclass(frozen=True)
class Luogo:
    nome: str
    chiave: str
    tipo: str
    circoscrizione: str


def _vie(civici: pd.DataFrame) -> list[Luogo]:
    """civici: colonne via, circoscrizione (una riga per civico)."""
    out = []
    conteggi = civici.groupby(["via", "circoscrizione"]).size().unstack(fill_value=0)
    quote = conteggi.div(conteggi.sum(axis=1), axis=0)
    for via, riga in quote.iterrows():
        circ = riga.idxmax()
        if riga[circ] < SOGLIA_VIA:
            continue
        chiave = normalizza(via)
        parole = chiave.split()
        if len(parole) < 2 or parole[0] not in TIPI_VIA:
            continue
        out.append(Luogo(via.title(), chiave, "via", circ))
        ultima = parole[-1]
        if len(parole) > 2 and len(ultima) >= 4 and not re.fullmatch(r"[ivxlc]+", ultima):
            out.append(Luogo(f"{parole[0]} {ultima}".title(), f"{parole[0]} {ultima}", "via", circ))
    return out


def _quartieri(nomi_circ: dict[str, str]) -> list[Luogo]:
    out = []
    fonti = [nomi_circ, segmenti().circoscrizioni]
    for nomi in fonti:
        for circ, nome in nomi.items():
            for q in re.split(r"[,\-]", nome):
                chiave = normalizza(q)
                if not chiave:
                    continue
                if chiave in QUARTIERI_AMBIGUI:
                    for prefisso in ("quartiere", "borgo", "zona"):
                        out.append(Luogo(q.strip(), f"{prefisso} {chiave}", "quartiere", circ))
                else:
                    out.append(Luogo(q.strip(), chiave, "quartiere", circ))
    return out


def _geoportale(nome: str, colonna: str, tipo: str, prefissi: tuple[str, ...]) -> list[Luogo]:
    percorso = scarica(GEOPORTALE.format(nome), FONTE_RAW)
    # Il primo livello (le aree) ha nome e circoscrizione; quello a punti ha altre colonne.
    livello = gpd.list_layers(percorso)["name"].tolist()[0]
    g = gpd.read_file(percorso, layer=livello, ignore_geometry=True)
    out = []
    for r in g.itertuples():
        denom = str(getattr(r, colonna) or "").strip()
        try:
            circ = normalizza_circoscrizione(r.CIRCOSCRIZ)
        except ValueError:
            continue
        chiave = normalizza(denom)
        if not chiave or chiave in ("comunale", "statale"):
            continue
        if prefissi:
            for p in prefissi:
                out.append(Luogo(f"{p.title()} {denom}", f"{p} {chiave}", tipo, circ))
        elif len(chiave.split()) >= 2:
            out.append(Luogo(denom, chiave, tipo, circ))
    return out


def costruisci(civici: pd.DataFrame, nomi_circ: dict[str, str], con_geoportale=True) -> list[Luogo]:
    luoghi = _vie(civici) + _quartieri(nomi_circ)
    if con_geoportale:
        luoghi += _geoportale("mercati", "DENOM", "mercato", ("mercato", "mercato di"))
        luoghi += _geoportale("impianti_sportivi", "DENOM_IMP", "impianto", ())
        luoghi += _geoportale("biblioteche", "DENOMINAZ", "biblioteca", ())
        luoghi += _geoportale("scuole", "DENOMINAZ", "scuola", ("scuola", "istituto", "liceo"))
    # Una chiave che porta a più circoscrizioni è ambigua: si scarta.
    per_chiave: dict[str, set[str]] = defaultdict(set)
    for luogo in luoghi:
        per_chiave[luogo.chiave].add(luogo.circoscrizione)
    visti = set()
    out = []
    for luogo in luoghi:
        if len(per_chiave[luogo.chiave]) == 1 and luogo.chiave not in visti:
            visti.add(luogo.chiave)
            out.append(luogo)
    return out


def leggi_civici() -> pd.DataFrame:
    grezzi = pd.read_csv(scarica(sez.URL_CIVICI, sez.FONTE_CIVICI), dtype=str)
    return pd.DataFrame(
        {"via": grezzi["VIA"].str.strip(), "circoscrizione": grezzi["CIRCOSCRIZIONE"].str.strip()}
    ).dropna()


def salva(con: duckdb.DuckDBPyConnection, luoghi: list[Luogo]) -> int:
    df = pd.DataFrame([vars(luogo) for luogo in luoghi])
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM luogo")
        con.register("_luoghi", df)
        con.execute(
            "INSERT INTO luogo (nome, chiave, tipo, circoscrizione) "
            "SELECT nome, chiave, tipo, circoscrizione FROM _luoghi"
        )
        con.unregister("_luoghi")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(df)


class Geolocalizzatore:
    """Trova i luoghi del dizionario in un testo e sceglie la circoscrizione."""

    def __init__(self, luoghi: list[Luogo]):
        self.indice = {luogo.chiave: luogo for luogo in luoghi}

    @classmethod
    def da_db(cls, con: duckdb.DuckDBPyConnection) -> Geolocalizzatore:
        righe = con.execute("SELECT nome, chiave, tipo, circoscrizione FROM luogo").fetchall()
        return cls([Luogo(*r) for r in righe])

    def trova(self, testo: str) -> list[Luogo]:
        parole = normalizza(testo).split()
        trovati = []
        i = 0
        while i < len(parole):
            # Si preferisce la corrispondenza più lunga a partire da ogni parola.
            for n in range(min(MAX_PAROLE, len(parole) - i), 0, -1):
                luogo = self.indice.get(" ".join(parole[i : i + n]))
                if luogo:
                    trovati.append(luogo)
                    i += n
                    break
            else:
                i += 1
        return trovati

    def circoscrizione(self, testo: str) -> tuple[str | None, list[Luogo]]:
        """Circoscrizione del testo: unica, oppure nettamente prevalente (almeno il doppio)."""
        trovati = self.trova(testo)
        if not trovati:
            return None, []
        conteggi = Counter(luogo.circoscrizione for luogo in trovati).most_common()
        if len(conteggi) == 1 or conteggi[0][1] >= 2 * conteggi[1][1]:
            return conteggi[0][0], trovati
        return None, trovati


def geolocalizza(con: duckdb.DuckDBPyConnection, solo_nuovi: bool = True) -> dict[str, int]:
    """Assegna area_id e luogo ai documenti (titolo + sintesi + testo)."""
    geo = Geolocalizzatore.da_db(con)
    if not geo.indice:
        raise RuntimeError(
            "Dizionario dei luoghi vuoto: eseguire `uv run python -m app.temi luoghi`"
        )
    ids = dict(con.execute("SELECT codice, id FROM area WHERE tipo = 'circoscrizione'").fetchall())
    filtro = "WHERE luogo IS NULL AND area_id IS NULL" if solo_nuovi else ""
    righe = con.execute(
        f"SELECT id, coalesce(titolo, '') || ' ' || coalesce(sintesi, '') || ' ' || "
        f"coalesce(testo, '') FROM documento {filtro}"
    ).fetchall()
    assegnati = 0
    for id_doc, testo in righe:
        circ, trovati = geo.circoscrizione(testo)
        nomi = ", ".join(dict.fromkeys(luogo.nome for luogo in trovati))[:200] or None
        con.execute(
            "UPDATE documento SET area_id = ?, luogo = ? WHERE id = ?",
            [ids.get(circ) if circ else None, nomi, id_doc],
        )
        assegnati += circ is not None
    return {"documenti": len(righe), "assegnati": assegnati}
