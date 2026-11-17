"""Esecuzione delle simulazioni: flusso chat e flusso API con un SDK finto (nessuna spesa)."""

import json
import re
from types import SimpleNamespace

import pytest
from anthropic.types import Usage

from app.analysis import demografia as dm
from app.core import db
from app.core.config import Impostazioni, PrezziLLM, PrezzoModello
from app.llm import simulazione as sim
from app.llm.client import ClientLLM, TettoSpesaSuperato

MODELLO = "modello-prova"
PREZZI = PrezziLLM(
    sconto_batch=0.5,
    modelli={MODELLO: PrezzoModello(input=3.0, output=15.0, cache_lettura=0.3,
                                    cache_scrittura_5m=3.75, cache_scrittura_1h=6.0)},
)  # fmt: skip
SEGMENTI = [
    {"fascia_eta": "18-29", "condizione": "studente", "area_di_voto": "centrosinistra"},
    {"fascia_eta": "65+", "condizione": "pensionato", "area_di_voto": "centrodestra"},
]


def _imp(soglia=5.0, tetto=100.0):
    return Impostazioni(
        _env_file=None,
        modello_simulazione=MODELLO,
        modello_sintesi=MODELLO,
        modello_classificazione=MODELLO,
        tetto_spesa_mensile_eur=tetto,
        soglia_conferma_run_eur=soglia,
        cambio_usd_eur=1.0,
    )


def popola(c):
    """Due circoscrizioni con maggiorenni e pesi per i due segmenti di prova."""
    for codice, nome, adulti in (("3", "San Paolo, Cenisia", 300), ("4", "San Donato", 100)):
        (aid,) = c.execute(
            "INSERT INTO area (tipo, codice, nome) VALUES ('circoscrizione', ?, ?) RETURNING id",
            [codice, nome],
        ).fetchone()
        c.execute(
            "INSERT INTO demografia VALUES (?, 2025, 'pop_eta_040', ?, ?)", [aid, adulti, dm.COMUNE]
        )
        for i, s in enumerate(SEGMENTI):
            (sid,) = c.execute(
                "INSERT INTO segmento (definizione) VALUES (?) RETURNING id", [json.dumps(s)]
            ).fetchone()
            c.execute(
                "INSERT INTO segmento_peso VALUES (?, ?, 2025, 'comunali', ?)",
                [sid, aid, 0.1 if i == 0 else 0.3],
            )


@pytest.fixture
def con(tmp_path):
    c = db.connetti(tmp_path / "t.duckdb")
    db.crea_schema(c)
    popola(c)
    yield c
    c.close()


def _richiesta(**kw):
    base = {"proposta": "Un nuovo parco", "candidato": "sindaco", "aree": ["3"],
            "segmenti": SEGMENTI, "persone": 3, "seed": 7}  # fmt: skip
    return sim.Richiesta(**{**base, **kw})


def _valutazione(g):
    effetto = "avvicina" if g >= 4 else "nessuno"
    return {"gradimento": g, "effetto_voto": effetto, "timori": ["costi alti"],
            "parole_ricordate": ["parco"], "reazione": f"Voto {g}"}  # fmt: skip


def _risposta_blocco(run, n, con_b=False):
    blocco = next(b for b in run["parametri"]["blocchi"] if b["n"] == n)
    segmenti = []
    for i in blocco["indici"]:
        persone = [
            {"codice": p["codice"], "a": _valutazione(4 if i == 0 else 2),
             **({"b": _valutazione(5)} if con_b else {})}
            for p in run["parametri"]["panel"][blocco["area"]][str(i)]
        ]  # fmt: skip
        segmenti.append({"indice": i, "persone": persone})
    return "Ecco il risultato:\n```json\n" + json.dumps({"segmenti": segmenti}) + "\n```"


# --- creazione --------------------------------------------------------------


def test_crea_ripetibile(con):
    a = sim.carica(con, sim.crea(con, _richiesta(), "chat"))
    b = sim.carica(con, sim.crea(con, _richiesta(), "chat"))
    assert a["parametri"]["panel"] == b["parametri"]["panel"]
    assert sim.prompt_chat(a, 1).split("\n", 1)[1] == sim.prompt_chat(b, 1).split("\n", 1)[1]
    assert a["stato"] == "in_attesa" and a["origine"] == "chat" and a["seed"] == 7
    assert a["parametri"]["pesi"]["3"] == pytest.approx({"0": 0.25, "1": 0.75})
    assert "non usata" in a["parametri"]["temperatura"]


def test_crea_valida_input(con):
    with pytest.raises(sim.ErroreSimulazione, match="vuota"):
        sim.crea(con, _richiesta(proposta="  "), "chat")
    with pytest.raises(sim.ErroreSimulazione, match="sconosciute"):
        sim.crea(con, _richiesta(aree=["9"]), "chat")


def test_blocchi_da_cinque_segmenti():
    blocchi = sim._blocchi(["1", "2"], 7)
    assert [(b["area"], b["indici"]) for b in blocchi] == [
        ("1", [0, 1, 2, 3, 4]), ("1", [5, 6]), ("2", [0, 1, 2, 3, 4]), ("2", [5, 6]),
    ]  # fmt: skip


# --- flusso chat ------------------------------------------------------------


def test_prompt_chat_contenuto(con):
    run = sim.carica(con, sim.crea(con, _richiesta(), "chat"))
    p = sim.prompt_chat(run, 1)
    assert "Simulazione IA, non è un sondaggio" in p
    assert "Un nuovo parco" in p and "P01" in p and '"segmenti"' in p
    with pytest.raises(sim.ErroreSimulazione):
        sim.prompt_chat(run, 2)


def test_flusso_chat_completo(con):
    sid = sim.crea(con, _richiesta(aree=["3", "4"]), "chat")
    run = sim.carica(con, sid)
    esito = sim.importa_chat(con, sid, 1, _risposta_blocco(run, 1))
    assert esito["completati"] == [1] and sim.carica(con, sid)["stato"] == "in_attesa"
    sim.importa_chat(con, sid, 2, _risposta_blocco(run, 2))
    run = sim.carica(con, sid)
    assert run["stato"] == "completata" and run["costo"] == 0
    tot = run["risultati"]["aggregati"]["a"]["totale"]
    # segmento 0 (peso 0,25) gradimento 4, segmento 1 (0,75) gradimento 2
    assert tot["gradimento_medio"] == pytest.approx(2.5)
    assert [a["peso"] for a in run["risultati"]["aggregati"]["a"]["aree"]] == [0.75, 0.25]


def test_importa_chat_rifiuta_risposte_incomplete(con):
    sid = sim.crea(con, _richiesta(), "chat")
    run = sim.carica(con, sid)
    dati = json.loads(_risposta_blocco(run, 1).split("```json\n")[1].split("```")[0])
    dati["segmenti"][0]["persone"].pop()
    with pytest.raises(sim.ErroreSimulazione, match="mancanti"):
        sim.importa_chat(con, sid, 1, json.dumps(dati))
    dati["segmenti"].pop(0)
    with pytest.raises(sim.ErroreSimulazione, match="Mancano i segmenti"):
        sim.importa_chat(con, sid, 1, json.dumps(dati))
    with pytest.raises(sim.ErroreSimulazione, match="JSON"):
        sim.importa_chat(con, sid, 1, "non è json")
    # niente salvato
    assert sim.carica(con, sid)["risultati"]["risposte"] == {}


def test_ab_e_sintesi_chat(con):
    sid = sim.crea(con, _richiesta(proposta_b="Un parco con più alberi"), "chat")
    run = sim.carica(con, sid)
    with pytest.raises(sim.ErroreSimulazione, match="proposta B"):
        sim.importa_chat(con, sid, 1, _risposta_blocco(run, 1, con_b=False))
    sim.importa_chat(con, sid, 1, _risposta_blocco(run, 1, con_b=True))
    run = sim.carica(con, sid)
    assert run["risultati"]["aggregati"]["ab"]["totale"]["gradimento_medio"] == pytest.approx(2.5)
    p = sim.prompt_sintesi(run)
    assert "Chi apprezza" in p and "Voto 4" not in p  # solo aggregati, niente frasi
    sim.importa_sintesi(con, sid, "  Sintesi di prova  ")
    assert sim.carica(con, sid)["risultati"]["sintesi"] == "Sintesi di prova"


# --- flusso API -------------------------------------------------------------


class SDKFinto:
    """Risponde a ogni segmento con valutazioni valide per i codici del panel nel prompt."""

    def __init__(self, gradimento=3):
        self.chiamate = []
        self.g = gradimento
        self.messages = SimpleNamespace(
            create=self._create,
            batches=SimpleNamespace(
                create=self._batch, retrieve=self._stato, results=self._risultati
            ),
        )
        self._batch_richieste = []

    def _risposta(self, params):
        testo = params["messages"][0]["content"][-1]["text"]
        codici = re.findall(r"^(P\d+):", testo, re.M)
        persone = [{"codice": c, "a": _valutazione(self.g)} for c in codici]
        return SimpleNamespace(
            usage=Usage(input_tokens=1000, output_tokens=500),
            content=[SimpleNamespace(type="text", text=json.dumps({"persone": persone}))],
            stop_reason="end_turn",
        )

    def _create(self, **kw):
        self.chiamate.append(kw)
        if "persone" not in json.dumps(kw.get("output_config", {})):
            return SimpleNamespace(
                usage=Usage(input_tokens=100, output_tokens=100),
                content=[SimpleNamespace(type="text", text="Sintesi API")],
                stop_reason="end_turn",
            )
        return self._risposta(kw)

    def _batch(self, requests):
        self._batch_richieste = requests
        return SimpleNamespace(id="batch_1")

    def _stato(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def _risultati(self, batch_id):
        for r in self._batch_richieste:
            msg = self._risposta(r["params"])
            yield SimpleNamespace(
                custom_id=r["custom_id"],
                result=SimpleNamespace(type="succeeded", message=msg),
            )


def _client(con, sdk, **kw):
    return ClientLLM(con, imp=_imp(**kw), prezzi=PREZZI, sdk=sdk)


def test_flusso_api(con):
    sid = sim.crea(con, _richiesta(), "api", imp=_imp())
    sdk = SDKFinto(gradimento=4)
    esito = sim.esegui_api(con, sid, _client(con, sdk), imp=_imp(), prezzi=PREZZI)
    assert esito["stato"] == "completata" and len(sdk.chiamate) == 2
    chiamata = sdk.chiamate[0]
    assert chiamata["model"] == MODELLO and "temperature" not in chiamata
    assert chiamata["system"][0]["cache_control"] == {"type": "ephemeral"}
    run = sim.carica(con, sid)
    assert run["stato"] == "completata" and run["modello"] == MODELLO
    # 2 chiamate × (1000 × 3 + 500 × 15) / 1e6 $
    assert run["costo"] == pytest.approx(2 * 0.0105)
    assert run["risultati"]["aggregati"]["a"]["totale"]["gradimento_medio"] == 4
    testo = sim.genera_sintesi_api(con, sid, _client(con, sdk))
    run = sim.carica(con, sid)
    assert testo == "Sintesi API" and run["risultati"]["sintesi"] == "Sintesi API"
    assert run["costo"] > 2 * 0.0105


def test_api_richiede_conferma_sopra_soglia(con):
    sid = sim.crea(con, _richiesta(persone=30), "api", imp=_imp())
    sdk = SDKFinto()
    imp = _imp(soglia=0.0001)
    with pytest.raises(sim.RichiestaConferma):
        sim.esegui_api(con, sid, _client(con, sdk, soglia=0.0001), imp=imp, prezzi=PREZZI)
    assert sdk.chiamate == []
    sim.esegui_api(con, sid, _client(con, sdk), conferma=True, imp=imp, prezzi=PREZZI)
    assert sim.carica(con, sid)["stato"] == "completata"


def test_api_rispetta_tetto(con):
    sid = sim.crea(con, _richiesta(), "api", imp=_imp())
    sdk = SDKFinto()
    with pytest.raises(TettoSpesaSuperato):
        sim.esegui_api(con, sid, _client(con, sdk, tetto=0.0001), imp=_imp(), prezzi=PREZZI)
    assert sdk.chiamate == []


def test_api_batch_oltre_soglia(con, monkeypatch):
    monkeypatch.setattr(sim, "SOGLIA_BATCH", 1)
    sid = sim.crea(con, _richiesta(), "api", imp=_imp())
    sdk = SDKFinto(gradimento=2)
    client = _client(con, sdk)
    esito = sim.esegui_api(con, sid, client, imp=_imp(), prezzi=PREZZI)
    assert esito["stato"] == "in_attesa" and esito["batch"] is True
    assert len(sdk._batch_richieste) == 2 and sdk.chiamate == []
    assert sim.raccogli_batch(con, sid, client)["stato"] == "completata"
    run = sim.carica(con, sid)
    assert run["stato"] == "completata"
    assert run["costo"] == pytest.approx(2 * 0.0105 * 0.5)  # sconto batch
