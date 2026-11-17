import pytest
from pydantic import ValidationError

from app.llm import prompt_simulazione as ps
from app.llm.persone import PersonaSintetica

PANEL = [
    PersonaSintetica("P01", "donna", 35, "Cenisia", ("ha figli piccoli", "va in bici")),
    PersonaSintetica("P02", "uomo", 40, "San Paolo", ("vive in affitto", "lavora fuori Torino")),
]


def _val(g=4, e="avvicina"):
    return {"gradimento": g, "effetto_voto": e, "timori": ["costi"], "parole_ricordate": ["parco"],
            "reazione": "Mi piace."}  # fmt: skip


def _risposta(con_b=False, codici=("P01", "P02")):
    persone = [
        {"codice": c, "a": _val(), **({"b": _val(2, "nessuno")} if con_b else {})} for c in codici
    ]
    return ps.RispostaSegmento.model_validate({"indice": 0, "persone": persone})


def test_valutazione_fuori_scala():
    with pytest.raises(ValidationError):
        ps.Valutazione.model_validate(_val(g=6))
    with pytest.raises(ValidationError):
        ps.Valutazione.model_validate(_val(e="forse"))
    with pytest.raises(ValidationError):
        ps.Valutazione.model_validate({**_val(), "timori": ["a", "b", "c", "d"]})


def test_valida_panel_completo():
    ps.valida(_risposta(), PANEL, con_b=False)
    with pytest.raises(ps.ErroreRisposta, match="mancanti"):
        ps.valida(_risposta(codici=("P01",)), PANEL, con_b=False)
    with pytest.raises(ps.ErroreRisposta, match="inattese"):
        ps.valida(_risposta(codici=("P01", "P02", "P03")), PANEL, con_b=False)


def test_variante_b_obbligatoria():
    with pytest.raises(ps.ErroreRisposta, match="proposta B"):
        ps.valida(_risposta(con_b=False), PANEL, con_b=True)
    ps.valida(_risposta(con_b=True), PANEL, con_b=True)


def test_schemi():
    assert "b" not in ps.schema_risposta_api(False)["properties"]["persone"]["items"]["properties"]
    assert "b" in ps.schema_risposta_api(True)["properties"]["persone"]["items"]["required"]
    assert ps.schema_risposta_chat(False)["required"] == ["segmenti"]


def test_testi():
    assert "non vanno a votare" in ps.descrizione_segmento(
        {"fascia_eta": "18-29", "condizione": "studente", "area_di_voto": "astensione abituale"}
    )
    t = ps.testo_proposta("Parco", "Parco verde", "Mario")
    assert "Proposta B" in t and "valuta sia A sia B" in t
    assert "P01: donna, 35 anni, Cenisia" in ps.testo_panel(PANEL)
