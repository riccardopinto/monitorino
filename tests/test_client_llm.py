"""Test del client LLM con un SDK finto: nessuna chiamata di rete, nessuna spesa."""

from types import SimpleNamespace

import pytest
from anthropic.types import CacheCreation, Usage

from app.core import db
from app.core.config import Impostazioni, PrezziLLM, PrezzoModello
from app.llm.client import ClientLLM, ModelloSenzaPrezzo, TettoSpesaSuperato, costo_usd

MODELLO = "modello-prova"
PREZZO = PrezzoModello(
    input=1.0, output=2.0, cache_lettura=0.1, cache_scrittura_5m=1.25, cache_scrittura_1h=2.0
)


class SDKFinto:
    def __init__(self, usage: Usage):
        self.chiamate: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)
        self._usage = usage

    def _create(self, **kwargs):
        self.chiamate.append(kwargs)
        return SimpleNamespace(usage=self._usage, content=[])


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    yield c
    c.close()


def _imp(tetto: float = 10.0) -> Impostazioni:
    return Impostazioni(
        _env_file=None,
        modello_simulazione=MODELLO,
        modello_sintesi=MODELLO,
        modello_classificazione="modello-senza-prezzo",
        tetto_spesa_mensile_eur=tetto,
        soglia_conferma_run_eur=1.0,
        cambio_usd_eur=0.5,
    )


def _client(con, usage, tetto=10.0):
    prezzi = PrezziLLM(sconto_batch=0.5, modelli={MODELLO: PREZZO})
    sdk = SDKFinto(usage)
    return ClientLLM(con, imp=_imp(tetto), prezzi=prezzi, sdk=sdk), sdk


def test_costo_semplice():
    # 1M input a 1 $ + 1M output a 2 $
    assert costo_usd(PREZZO, token_input=1_000_000, token_output=1_000_000) == 3.0


def test_costo_con_cache_e_batch():
    c = costo_usd(
        PREZZO,
        token_input=0,
        token_output=0,
        cache_lettura=1_000_000,
        cache_scrittura_5m=1_000_000,
        cache_scrittura_1h=1_000_000,
    )
    assert c == pytest.approx(0.1 + 1.25 + 2.0)
    batch = costo_usd(PREZZO, token_input=1_000_000, token_output=0, batch=True, sconto_batch=0.5)
    assert batch == 0.5


def test_tariffa_prompt_lungo():
    p = PREZZO.model_copy(update={"soglia_prompt_lungo": 100, "input_lungo": 5.0})
    assert costo_usd(p, token_input=100, token_output=0) == 100 * 1.0 / 1e6
    assert costo_usd(p, token_input=101, token_output=0) == 101 * 5.0 / 1e6


def test_messaggio_registra_uso(con):
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_creation=CacheCreation(
            ephemeral_5m_input_tokens=1_000_000, ephemeral_1h_input_tokens=0
        ),
    )
    client, sdk = _client(con, usage)
    client.messaggio(
        modulo="test", ruolo="simulazione", max_tokens=10, messages=[], utente="analista"
    )

    assert sdk.chiamate[0]["model"] == MODELLO
    riga = con.execute(
        "SELECT modulo, modello, token_input, token_output, cache_lettura, cache_scrittura, "
        "batch, costo_eur, utente FROM uso_llm"
    ).fetchone()
    # USD: 1 + 1 (output) + 0.1 + 1.25 = 3.35, in EUR con cambio 0.5
    assert riga[:7] == ("test", MODELLO, 1_000_000, 500_000, 1_000_000, 1_000_000, False)
    assert riga[7] == pytest.approx(3.35 * 0.5)
    assert riga[8] == "analista"
    assert client.spesa_mese_eur() == pytest.approx(3.35 * 0.5)


def test_tetto_blocca_le_chiamate(con):
    usage = Usage(input_tokens=1_000_000, output_tokens=0)
    client, sdk = _client(con, usage, tetto=1.0)
    client.messaggio(modulo="test", ruolo="simulazione", max_tokens=10, messages=[])  # 0,50 €
    client.messaggio(modulo="test", ruolo="simulazione", max_tokens=10, messages=[])  # 1,00 €
    with pytest.raises(TettoSpesaSuperato):
        client.messaggio(modulo="test", ruolo="simulazione", max_tokens=10, messages=[])
    assert len(sdk.chiamate) == 2


def test_stima_oltre_tetto(con):
    client, _ = _client(con, Usage(input_tokens=0, output_tokens=0), tetto=1.0)
    stima = client.stima_eur("simulazione", 4_000_000, 0)  # 4 $ = 2 €
    assert stima == 2.0
    with pytest.raises(TettoSpesaSuperato):
        client.verifica_tetto(stima)


def test_modello_senza_prezzo_non_chiama_api(con):
    client, sdk = _client(con, Usage(input_tokens=0, output_tokens=0))
    with pytest.raises(ModelloSenzaPrezzo):
        client.messaggio(modulo="test", ruolo="classificazione", max_tokens=10, messages=[])
    assert sdk.chiamate == []
