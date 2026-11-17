import pandas as pd

from app.core import db
from app.temi import luoghi as lg


def _civici():
    righe = (
        [("VIA PIETRO PALMIERI", "3")] * 9
        + [("VIA PIETRO PALMIERI", "4")] * 1
        + [("CORSO FRANCIA", "3")] * 5
        + [("CORSO FRANCIA", "4")] * 5  # divisa a metà: esclusa
        + [("VIA GIUSEPPE PALMIERI", "8")] * 3  # stessa forma breve "via palmieri"
        + [("VIA NIZZA", "8")] * 4
    )
    return pd.DataFrame(righe, columns=["via", "circoscrizione"])


def _luoghi():
    nomi = {str(i): "Nome" for i in range(1, 9)}
    nomi.update({"3": "San Paolo - Cenisia", "7": "Aurora, Vanchiglia"})
    return lg.costruisci(_civici(), nomi, con_geoportale=False)


def test_dizionario():
    chiavi = {luogo.chiave: luogo.circoscrizione for luogo in _luoghi()}
    assert chiavi["via pietro palmieri"] == "3"
    assert "corso francia" not in chiavi  # sotto l'80%
    assert "via palmieri" not in chiavi  # forma breve ambigua tra 3 e 8
    assert chiavi["via nizza"] == "8"
    assert chiavi["cenisia"] == "3"
    assert "aurora" not in chiavi and chiavi["borgo aurora"] == "7"  # nome troppo comune


def test_geolocalizzazione():
    g = lg.Geolocalizzatore(_luoghi())
    assert g.circoscrizione("Incidente in Via Pietro Palmieri, a Cenisia")[0] == "3"
    assert g.circoscrizione("Lavori in via Nizza e a Vanchiglia")[0] is None  # 1 a 1: città
    assert g.circoscrizione("Aurora boreale vista da Torino")[0] is None
    circ, trovati = g.circoscrizione("Via Nizza, poi via Nizza e Cenisia")
    assert circ == "8" and len(trovati) == 3


def test_geolocalizza_documenti(tmp_path):
    con = db.connetti(tmp_path / "g.duckdb")
    db.crea_schema(con)
    con.execute("INSERT INTO area (id, tipo, codice) VALUES (30, 'circoscrizione', '3')")
    lg.salva(con, _luoghi())
    con.execute(
        "INSERT INTO documento (fonte, titolo, sintesi) VALUES "
        "('x', 'Nuovo parco a Cenisia', NULL), ('x', 'Notizia senza luoghi', 'nulla')"
    )
    esito = lg.geolocalizza(con)
    assert esito == {"documenti": 2, "assegnati": 1}
    righe = con.execute("SELECT area_id, luogo FROM documento ORDER BY id").fetchall()
    assert righe == [(30, "Cenisia"), (None, None)]
    con.close()
