import json
from types import SimpleNamespace

import pytest
from anthropic.types import Usage

from app.core import db
from app.core.config import Impostazioni, PrezziLLM, PrezzoModello
from app.llm import classificazione as cl
from app.llm import prompt_temi as pt
from app.llm.client import ClientLLM
from app.temi import chat

TEMA = "verde pubblico e parchi"


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    c.execute("INSERT INTO area (id, tipo, codice) VALUES (13, 'circoscrizione', '3')")
    c.execute(
        "INSERT INTO documento (id, fonte, tipo_fonte, titolo, sintesi, testo, data) VALUES "
        "(1, 'Testata', 'news', 'Nuovo parco a San Paolo', 'Sommario del feed', NULL, "
        "'2026-11-15'), "
        "(2, 'Bluesky', 'social', NULL, NULL, 'Il parco sotto casa è sporco', '2026-11-16'), "
        "(3, 'Testata', 'news', 'Notizia di Orbassano', NULL, NULL, '2026-11-14')"
    )
    yield c
    c.close()


def _voce(id_, **kw):
    v = {"id": id_, "pertinente": True, "tema": TEMA, "sentiment": 1, "circoscrizione": None,
         "sintesi": "Sintesi neutra."}  # fmt: skip
    v.update(kw)
    return v


def test_validazione():
    pt.Classificazione.model_validate(_voce(1))
    with pytest.raises(ValueError):
        pt.Classificazione.model_validate(_voce(1, tema="inventato"))
    with pytest.raises(ValueError):
        pt.Classificazione.model_validate(_voce(1, sentiment=3))
    with pytest.raises(ValueError):
        pt.Classificazione.model_validate(_voce(1, circoscrizione="9"))
    assert pt.Classificazione.model_validate(_voce(1, circoscrizione="")).circoscrizione is None


@pytest.mark.parametrize(
    "testo",
    [
        json.dumps({"classificazioni": [_voce(1)]}),
        json.dumps([_voce(1)]),
        "Ecco il risultato:\n```json\n" + json.dumps({"classificazioni": [_voce(1)]}) + "\n```",
    ],
)
def test_estrai_json(testo):
    assert pt.estrai_json(testo)[0]["id"] == 1


def test_applica_regole(con):
    con.execute("UPDATE documento SET area_id = 13 WHERE id = 1")  # trovata dal dizionario
    esito = pt.applica(
        con,
        [_voce(1, circoscrizione="8"), _voce(2, circoscrizione="3"), _voce(3, pertinente=False),
         _voce(99), _voce(2, tema="sbagliato")],
        origine="chat",
    )  # fmt: skip
    assert esito["applicati"] == [1, 2, 3]
    assert esito["sconosciuti"] == [99]
    assert len(esito["errori"]) == 1
    righe = con.execute(
        "SELECT id, area_id, sintesi, pertinente, classificato_da FROM documento ORDER BY id"
    ).fetchall()
    assert righe[0] == (1, 13, "Sommario del feed", True, "chat")  # area e sintesi del feed restano
    assert righe[1][1:3] == (13, "Sintesi neutra.")  # social: area e sintesi dal modello
    assert righe[2][3] is False
    # una seconda importazione non sovrascrive
    assert pt.applica(con, [_voce(1, tema="politica e candidature")], "chat")[
        "gia_classificati"
    ] == [1]


def test_esporta_e_importa(con, tmp_path):
    file = chat.esporta(con, tmp_path, per_file=2)
    assert len(file) == 2
    testo = file[0].read_text(encoding="utf-8")
    assert "[id 2] Bluesky (social)" in testo and TEMA in testo
    assert "```json" in testo
    esito = chat.importa(con, json.dumps({"classificazioni": [_voce(1), _voce(2)]}))
    assert esito["applicati"] == [1, 2]
    # il prossimo export contiene solo il documento non classificato
    assert "[id 3]" in chat.esporta(con, tmp_path / "b")[0].read_text(encoding="utf-8")


class SDKFinto:
    def __init__(self):
        self.creati = []
        batches = SimpleNamespace(
            create=self._create, retrieve=self._retrieve, results=self._results
        )
        self.messages = SimpleNamespace(batches=batches)

    def _create(self, requests):
        self.creati.append(requests)
        return SimpleNamespace(id="batch_1")

    def _retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def _results(self, batch_id):
        richiesta = self.creati[-1][0]
        ids = [
            int(x.split("]")[0])
            for x in richiesta["params"]["messages"][0]["content"].split("[id ")[1:]
        ]
        testo = json.dumps({"classificazioni": [_voce(i) for i in ids]})
        msg = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=testo)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=1000, output_tokens=200),
        )
        yield SimpleNamespace(
            custom_id="gruppo-0", result=SimpleNamespace(type="succeeded", message=msg)
        )


def test_flusso_batch(con, tmp_path):
    imp = Impostazioni(
        _env_file=None, modello_simulazione="m", modello_sintesi="m", modello_classificazione="m",
        tetto_spesa_mensile_eur=10, soglia_conferma_run_eur=1, cambio_usd_eur=1,
    )  # fmt: skip
    prezzi = PrezziLLM(
        sconto_batch=0.5,
        modelli={
            "m": PrezzoModello(
                input=1, output=2, cache_lettura=0.1, cache_scrittura_5m=1.25, cache_scrittura_1h=2
            )
        },
    )
    sdk = SDKFinto()
    client = ClientLLM(con, imp=imp, prezzi=prezzi, sdk=sdk)
    stato = tmp_path / "stato.json"
    inviato = cl.invia(con, client, stato)
    assert inviato["inviati"] == 3
    params = sdk.creati[0][0]["params"]
    assert params["model"] == "m"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert cl.invia(con, client, stato)["inviati"] == 0  # già in un batch in corso
    raccolti = cl.raccogli_conclusi(con, client, stato)
    assert raccolti == {"applicati": 3, "errori": 0, "batch_in_corso": 0}
    batch, costo = con.execute("SELECT batch, costo_eur FROM uso_llm").fetchone()
    assert batch is True and costo == pytest.approx((1000 * 1 + 200 * 2) / 1e6 * 0.5)


def test_senza_chiave_si_ferma(con, monkeypatch):
    from app.llm.client import ErroreLLM

    monkeypatch.setattr(cl, "impostazioni", lambda: SimpleNamespace(anthropic_api_key=None))
    with pytest.raises(ErroreLLM, match="esporta"):
        cl.classifica(con)
