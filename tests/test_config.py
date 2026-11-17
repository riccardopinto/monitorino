import pytest
from pydantic import ValidationError

from app.core import config


def test_yaml_reali_validi():
    c = config.candidati()
    assert c.sindaco.nome
    assert set(c.circoscrizioni) == set(config.CIRCOSCRIZIONI)
    assert config.segmenti().persone_per_segmento > 0
    assert config.fonti().conservazione_testi_giorni <= 30
    assert config.temi().temi
    assert config.prezzi_llm().modelli


def test_modelli_env_example_hanno_prezzi():
    """Ogni modello indicato in .env.example deve avere un prezzo in prezzi_llm.yaml."""
    righe = (config.RADICE / ".env.example").read_text(encoding="utf-8").splitlines()
    modelli = {r.split("=", 1)[1].strip() for r in righe if r.startswith("MODELLO_")}
    assert modelli <= set(config.prezzi_llm().modelli)


def test_conservazione_oltre_30_giorni_rifiutata():
    with pytest.raises(ValidationError):
        config.Fonti(news=[], istituzionali=[], social={}, conservazione_testi_giorni=60)


def test_segmento_con_valore_sconosciuto_rifiutato():
    dati = config.segmenti().model_dump()
    dati["segmenti_default"].append(
        {"fascia_eta": "18-29", "condizione": "astronauta", "area_di_voto": "M5S"}
    )
    with pytest.raises(ValidationError):
        config.Segmenti.model_validate(dati)


def test_impostazioni_senza_modelli_falliscono(monkeypatch):
    for nome in ("MODELLO_SIMULAZIONE", "MODELLO_SINTESI", "MODELLO_CLASSIFICAZIONE"):
        monkeypatch.delenv(nome, raising=False)
    with pytest.raises(ValidationError):
        config.Impostazioni(_env_file=None)
