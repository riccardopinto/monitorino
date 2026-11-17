import pytest

from app.analysis import simulazione as sa

SEG = [
    {"fascia_eta": "18-29", "condizione": "studente", "area_di_voto": "centrosinistra"},
    {"fascia_eta": "65+", "condizione": "pensionato", "area_di_voto": "centrodestra"},
]


def _p(g, e, timori=(), parole=(), reazione="frase"):
    return {"a": {"gradimento": g, "effetto_voto": e, "timori": list(timori),
                  "parole_ricordate": list(parole), "reazione": reazione}}  # fmt: skip


def _risposte():
    return {
        "3": {
            0: [
                _p(5, "avvicina", ["costi alti"], ["parco"], "Ottimo"),
                _p(4, "nessuno", [], ["verde"]),
            ],
            1: [
                _p(1, "allontana", ["costo troppo alto"], [], "Spreco"),
                _p(2, "nessuno", ["traffico"]),
            ],
        }
    }


def test_metriche_pesate():
    pesi = {"3": {0: 0.25, 1: 0.75}}
    ag = sa.aggrega(SEG, pesi, {"3": 1000}, _risposte())
    seg0 = ag["segmenti"][0]
    assert seg0["gradimento_medio"] == 4.5 and seg0["saldo"] == 50.0 and seg0["n"] == 2
    t = ag["totale"]
    # gradimento: 0,25 × 4,5 + 0,75 × 1,5 = 2,25
    assert t["gradimento_medio"] == pytest.approx(2.25)
    # avvicina 0,125 (metà del primo segmento), allontana 0,375: saldo −25 punti
    assert t["saldo"] == pytest.approx(-25.0)
    assert t["favorevoli_pct"] == pytest.approx(25.0)
    assert t["gradimento_dev"] > 0
    voti = {a["area_di_voto"]: a for a in ag["aree_di_voto"]}
    assert voti["centrodestra"]["saldo"] == -50.0


def test_aree_pesate_sui_maggiorenni():
    r = {"1": {0: [_p(5, "avvicina")]}, "2": {0: [_p(1, "allontana")]}}
    pesi = {"1": {0: 1.0}, "2": {0: 1.0}}
    ag = sa.aggrega(SEG, pesi, {"1": 300, "2": 100}, r)
    assert ag["totale"]["gradimento_medio"] == pytest.approx(5 * 0.75 + 1 * 0.25)
    assert [a["peso"] for a in ag["aree"]] == [0.75, 0.25]


def test_obiezioni_raggruppate():
    gruppi = sa.raggruppa_obiezioni(
        [("costi alti", 1), ("costo troppo alto", 1), ("traffico", 1), ("Costi alti", 1)]
    )
    assert gruppi[0]["menzioni"] == 3
    assert gruppi[0]["quota_pct"] == 75.0
    assert gruppi[1]["obiezione"] == "traffico"


def test_frasi_rappresentative():
    ag = sa.aggrega(SEG, {"3": {0: 0.5, 1: 0.5}}, {"3": 1}, _risposte())
    tipi = {(f["indice"], f["tipo"]) for f in ag["frasi"]}
    assert (0, "favorevole") in tipi and (0, "contraria") in tipi and (1, "tipica") in tipi


def test_confronto_ab():
    r = {"3": {0: [{**_p(2, "nessuno"), "b": {**_p(4, "avvicina")["a"]}}]}}
    a = sa.aggrega(SEG, {"3": {0: 1.0}}, {"3": 1}, r, "a")
    b = sa.aggrega(SEG, {"3": {0: 1.0}}, {"3": 1}, r, "b")
    d = sa.confronto_ab(a, b)
    assert d["totale"]["gradimento_medio"] == 2.0 and d["totale"]["saldo"] == 100.0


def test_testo_per_sintesi_solo_aggregati():
    ag = sa.aggrega(SEG, {"3": {0: 0.5, 1: 0.5}}, {"3": 1}, _risposte())
    t = sa.testo_per_sintesi("Un parco", None, {"a": ag}, SEG)
    assert "saldo" in t and "Ottimo" not in t  # niente frasi individuali
