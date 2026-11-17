import pandas as pd

from app.llm import persone

SEGMENTO = {
    "fascia_eta": "30-44",
    "condizione": "lavoratore dipendente",
    "area_di_voto": "centrosinistra",
}
POP_M = pd.Series({e: 100.0 for e in range(0, 100)})
POP_F = pd.Series({e: 300.0 for e in range(0, 100)})
NOME = "San Paolo - Cenisia - Pozzo Strada"


def _panel(seed=42, n=40):
    return persone.genera_panel(seed, SEGMENTO, "3", n, POP_M, POP_F, NOME)


def test_deterministico():
    assert _panel() == _panel()
    assert _panel(seed=1) != _panel(seed=2)


def test_coerenza_con_segmento_e_quote():
    p = _panel(n=400)
    assert all(30 <= x.eta <= 44 for x in p)
    assert {x.quartiere for x in p} == {"San Paolo", "Cenisia", "Pozzo Strada"}
    donne = sum(x.sesso == "donna" for x in p) / len(p)
    assert 0.65 < donne < 0.85  # quota attesa 0,75
    assert len({x.codice for x in p}) == len(p)


def test_tratti_non_contraddittori():
    for x in _panel(n=200):
        assert len(x.tratti) == 2
        gruppi = [next(i for i, g in enumerate(persone.TRATTI) if t in g) for t in x.tratti]
        assert gruppi[0] != gruppi[1]


def test_eta_senza_dati_demografici():
    vuota = pd.Series(dtype=float)
    p = persone.genera_panel(1, {**SEGMENTO, "fascia_eta": "65+"}, "3", 5, vuota, vuota, "")
    assert all(65 <= x.eta <= persone.ETA_MAX for x in p)
    assert p[0].quartiere == "circoscrizione 3"
