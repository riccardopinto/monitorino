"""Esecuzione delle simulazioni del laboratorio messaggi.

Ciclo di un run:
1. ``crea``: panel deterministico dal seed, contesto per area, pesi; riga in simulazione con
   stato "in_attesa";
2. risposte, in uno dei due modi:
   - chat: ``prompt_chat`` per ogni blocco (un'area, fino a 5 segmenti), poi ``importa_chat``;
   - API: ``esegui_api`` (chiamate parallele) oppure Message Batches oltre SOGLIA_BATCH;
3. ``completa``: aggregazione; stato "completata";
4. sintesi: ``genera_sintesi_api`` oppure ``prompt_sintesi`` + ``importa_sintesi``.
Tutte le chiamate all'API passano da ClientLLM (registro costi e tetto di spesa).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

import duckdb

from app.analysis import simulazione as sa
from app.core.config import Impostazioni, PrezziLLM, impostazioni, prezzi_llm
from app.llm import contesto as ctx
from app.llm import persone as ps_persone
from app.llm import prompt_simulazione as ps
from app.llm.client import ClientLLM, costo_usd

SEGMENTI_PER_BLOCCO = 5
CONCORRENZA = 4
SOGLIA_BATCH = 40
TOKEN_ISTRUZIONI = 700
TOKEN_CONTESTO = 500
TOKEN_PER_PERSONA_IN = 30
TOKEN_PER_PERSONA_OUT = 110
MODELLO_CHAT = "chat esterna (incollato a mano)"
COLONNE = (
    "id, timestamp, proposta, aree, segmenti, modello, parametri, risultati, costo, "
    "stato, origine, seed, variante_pesi, candidato"
)


class ErroreSimulazione(ValueError):
    pass


class RichiestaConferma(ErroreSimulazione):
    """Il costo stimato supera la soglia: serve una conferma esplicita."""

    def __init__(self, costo: float, soglia: float):
        super().__init__(
            f"Costo stimato {costo:.2f} € oltre la soglia di conferma di {soglia:.2f} €"
        )
        self.costo = costo


@dataclass
class Richiesta:
    proposta: str
    candidato: str  # chiave di config.elenco_candidati
    aree: list[str]
    segmenti: list[dict]
    persone: int = 10
    variante: str = "comunali"
    seed: int = 1
    proposta_b: str | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)


# --- creazione e lettura ----------------------------------------------------


def crea(
    con: duckdb.DuckDBPyConnection, r: Richiesta, origine: str, imp: Impostazioni | None = None
) -> int:
    if not r.proposta.strip():
        raise ErroreSimulazione("La proposta è vuota")
    if not r.aree or not r.segmenti:
        raise ErroreSimulazione("Servono almeno un'area e un segmento")
    if not 1 <= r.persone <= 30:
        raise ErroreSimulazione("Le persone per segmento devono essere tra 1 e 30")
    candidato = ctx.candidato(r.candidato)
    nomi = ctx.nomi_circoscrizioni(con)
    sconosciute = [a for a in r.aree if a not in nomi]
    if sconosciute:
        raise ErroreSimulazione(f"Circoscrizioni sconosciute: {sconosciute}")
    adulti = ctx.adulti_per_circoscrizione(con)
    panel: dict[str, dict[str, list[dict]]] = {}
    pesi: dict[str, dict[str, float]] = {}
    contesti: dict[str, str] = {}
    for area in r.aree:
        maschi, femmine = ctx.popolazione_per_eta(con, area)
        panel[area] = {
            str(i): [
                p.come_dict()
                for p in ps_persone.genera_panel(
                    r.seed, s, area, r.persone, maschi, femmine, nomi[area]
                )
            ]
            for i, s in enumerate(r.segmenti)
        }
        pesi[area] = {
            str(i): w for i, w in ctx.pesi_segmenti(con, area, r.variante, r.segmenti).items()
        }
        contesti[area] = ctx.contesto_area(con, area, nomi[area])
    parametri = {
        "versione_metodo": ps.VERSIONE_METODO,
        "temperatura": "non usata (non supportata dall'API)",
        "persone_per_segmento": r.persone,
        "proposta_b": r.proposta_b,
        "candidato_nome": candidato.nome,
        "profilo_candidato": ctx.profilo_candidato(candidato),
        "note": r.note,
        "pesi": pesi,
        "adulti": {a: adulti.get(a, 0.0) for a in r.aree},
        "panel": panel,
        "contesti": contesti,
        "istruzioni": ps.istruzioni(),
        "blocchi": _blocchi(r.aree, len(r.segmenti)),
        "blocchi_completati": [],
        **r.extra,
    }
    modello = MODELLO_CHAT if origine == "chat" else (imp or impostazioni()).modello_simulazione
    (sid,) = con.execute(
        "INSERT INTO simulazione (proposta, aree, segmenti, modello, parametri, risultati, costo, "
        "stato, origine, seed, variante_pesi, candidato) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, 'in_attesa', ?, ?, ?, ?) RETURNING id",
        [
            r.proposta.strip(),
            json.dumps(r.aree),
            json.dumps(r.segmenti, ensure_ascii=False),
            modello,
            json.dumps(parametri, ensure_ascii=False),
            json.dumps({"risposte": {}}),
            origine,
            r.seed,
            r.variante,
            r.candidato,
        ],
    ).fetchone()
    return sid


def carica(con: duckdb.DuckDBPyConnection, sid: int) -> dict:
    riga = con.execute(
        f"SELECT {COLONNE} FROM simulazione WHERE id = ?",
        [sid],
    ).fetchone()
    if not riga:
        raise ErroreSimulazione(f"Simulazione {sid} non trovata")
    chiavi = COLONNE.split(", ")
    run = dict(zip(chiavi, riga, strict=True))
    for k in ("aree", "segmenti", "parametri", "risultati"):
        run[k] = json.loads(run[k]) if isinstance(run[k], str) else run[k]
    return run


def _salva(con: duckdb.DuckDBPyConnection, run: dict) -> None:
    con.execute(
        "UPDATE simulazione SET parametri = ?, risultati = ?, costo = ?, stato = ? WHERE id = ?",
        [
            json.dumps(run["parametri"], ensure_ascii=False),
            json.dumps(run["risultati"], ensure_ascii=False),
            run["costo"],
            run["stato"],
            run["id"],
        ],
    )


def _blocchi(aree: list[str], n_segmenti: int) -> list[dict]:
    out = []
    for area in aree:
        for inizio in range(0, n_segmenti, SEGMENTI_PER_BLOCCO):
            indici = list(range(inizio, min(inizio + SEGMENTI_PER_BLOCCO, n_segmenti)))
            out.append({"n": len(out) + 1, "area": area, "indici": indici})
    return out


def _persone(run: dict, area: str, indice: int) -> list[ps_persone.PersonaSintetica]:
    return [
        ps_persone.PersonaSintetica(**{**p, "tratti": tuple(p["tratti"])})
        for p in run["parametri"]["panel"][area][str(indice)]
    ]


def _testo_segmento(run: dict, area: str, indice: int) -> str:
    s = run["segmenti"][indice]
    return (
        f"Segmento {indice}: {ps.descrizione_segmento(s)}\n"
        f"Persone:\n{ps.testo_panel(_persone(run, area, indice))}"
    )


def _testo_proposta(run: dict) -> str:
    p = run["parametri"]
    return ps.testo_proposta(run["proposta"], p.get("proposta_b"), p["profilo_candidato"])


# --- flusso chat ------------------------------------------------------------


def prompt_chat(run: dict, n: int) -> str:
    blocchi = run["parametri"]["blocchi"]
    blocco = next((b for b in blocchi if b["n"] == n), None)
    if blocco is None:
        raise ErroreSimulazione(f"Blocco {n} inesistente (1-{len(blocchi)})")
    area = blocco["area"]
    con_b = bool(run["parametri"].get("proposta_b"))
    valutazione = {"gradimento": 3, "effetto_voto": "nessuno", "timori": ["..."],
                   "parole_ricordate": ["..."], "reazione": "..."}  # fmt: skip
    esempio_persona = {"codice": "P01", "a": valutazione}
    if con_b:
        esempio_persona["b"] = dict(esempio_persona["a"])
    esempio = {"segmenti": [{"indice": blocco["indici"][0], "persone": [esempio_persona]}]}
    segmenti = "\n\n".join(_testo_segmento(run, area, i) for i in blocco["indici"])
    n_persone = sum(len(run["parametri"]["panel"][area][str(i)]) for i in blocco["indici"])
    return f"""# Simulazione {run["id"]} · blocco {n} di {len(blocchi)} · circoscrizione {area}

{ps.DICITURA}.

{run["parametri"]["istruzioni"]}

## Contesto dell'area

{run["parametri"]["contesti"][area]}

## Proposta

{_testo_proposta(run)}

## Segmenti e persone ({len(blocco["indici"])} segmenti, {n_persone} persone)

{segmenti}

## Formato della risposta

Rispondi con un unico blocco JSON valido, senza testo prima o dopo. Un elemento in
"segmenti" per ognuno dei segmenti {blocco["indici"]}, e in ognuno tutte le sue persone con
il loro codice{" (valutazioni a e b)" if con_b else ""}. Esempio:

```json
{json.dumps(esempio, ensure_ascii=False, indent=2)}
```

Schema completo:

```json
{json.dumps(ps.schema_risposta_chat(con_b), ensure_ascii=False)}
```
"""


def _estrai_json(testo: str) -> Any:
    t = testo.strip()
    if m := re.search(r"```(?:json)?\s*(.*?)```", t, re.S):
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise ErroreSimulazione(f"JSON non valido: {e}") from e


def _registra_risposta(run: dict, area: str, risposta: ps.RispostaSegmento) -> None:
    con_b = bool(run["parametri"].get("proposta_b"))
    ps.valida(risposta, _persone(run, area, risposta.indice), con_b)
    run["risultati"]["risposte"].setdefault(area, {})[str(risposta.indice)] = [
        p.model_dump(exclude_none=True) for p in risposta.persone
    ]


def importa_chat(con: duckdb.DuckDBPyConnection, sid: int, n: int, testo: str) -> dict:
    """Importa la risposta di un blocco. Tutto o niente: un errore non salva nulla."""
    run = carica(con, sid)
    blocco = next((b for b in run["parametri"]["blocchi"] if b["n"] == n), None)
    if blocco is None:
        raise ErroreSimulazione(f"Blocco {n} inesistente")
    dati = _estrai_json(testo)
    voci = dati.get("segmenti") if isinstance(dati, dict) else None
    if not isinstance(voci, list):
        raise ErroreSimulazione('Formato non riconosciuto: atteso {"segmenti": [...]}')
    ricevuti = []
    for v in voci:
        try:
            r = ps.RispostaSegmento.model_validate(v)
        except Exception as e:  # noqa: BLE001
            raise ErroreSimulazione(f"Risposta non valida: {str(e)[:300]}") from e
        if r.indice not in blocco["indici"]:
            raise ErroreSimulazione(f"Il segmento {r.indice} non fa parte del blocco {n}")
        ricevuti.append(r)
    mancanti = set(blocco["indici"]) - {r.indice for r in ricevuti}
    if mancanti:
        raise ErroreSimulazione(f"Mancano i segmenti {sorted(mancanti)} del blocco {n}")
    for r in ricevuti:
        try:
            _registra_risposta(run, blocco["area"], r)
        except ps.ErroreRisposta as e:
            raise ErroreSimulazione(str(e)) from e
    if n not in run["parametri"]["blocchi_completati"]:
        run["parametri"]["blocchi_completati"].append(n)
    _salva(con, run)
    if len(run["parametri"]["blocchi_completati"]) == len(run["parametri"]["blocchi"]):
        completa(con, sid)
    return {
        "blocco": n,
        "completati": sorted(run["parametri"]["blocchi_completati"]),
        "totale_blocchi": len(run["parametri"]["blocchi"]),
    }


# --- aggregazione e sintesi -------------------------------------------------


def completa(con: duckdb.DuckDBPyConnection, sid: int) -> dict:
    run = carica(con, sid)
    risposte = {
        area: {int(i): persone for i, persone in per_seg.items()}
        for area, per_seg in run["risultati"]["risposte"].items()
    }
    pesi = {area: {int(i): w for i, w in p.items()} for area, p in run["parametri"]["pesi"].items()}
    adulti = run["parametri"]["adulti"]
    aggregati = {"a": sa.aggrega(run["segmenti"], pesi, adulti, risposte, "a")}
    if run["parametri"].get("proposta_b"):
        aggregati["b"] = sa.aggrega(run["segmenti"], pesi, adulti, risposte, "b")
        aggregati["ab"] = sa.confronto_ab(aggregati["a"], aggregati["b"])
    run["risultati"]["aggregati"] = aggregati
    run["stato"] = "completata"
    _salva(con, run)
    return aggregati


ISTRUZIONI_SINTESI = """Sei un analista di comunicazione politica. Ricevi i risultati \
aggregati di una simulazione con elettori sintetici (non è un sondaggio). Scrivi in italiano, \
in modo sobrio, quattro paragrafi brevi con questi titoli:
1. Chi apprezza
2. Chi si oppone e perché
3. Rischi
4. Suggerimenti di riformulazione
Ogni affermazione deve citare i numeri del riepilogo (gradimento, saldo, quote). Non \
inventare dati, non citare persone reali, non presentare i risultati come stime di voto. \
Massimo 350 parole."""


def prompt_sintesi(run: dict) -> str:
    if "aggregati" not in run["risultati"]:
        raise ErroreSimulazione("La simulazione non è ancora completa")
    riassunto = sa.testo_per_sintesi(
        run["proposta"],
        run["parametri"].get("proposta_b"),
        run["risultati"]["aggregati"],
        run["segmenti"],
    )
    return (
        f"{ISTRUZIONI_SINTESI}\n\n## Riepilogo numerico\n\n{riassunto}\n\n"
        "Rispondi solo con il testo della sintesi."
    )


def importa_sintesi(con: duckdb.DuckDBPyConnection, sid: int, testo: str) -> None:
    run = carica(con, sid)
    if "aggregati" not in run["risultati"]:
        raise ErroreSimulazione("La simulazione non è ancora completa")
    run["risultati"]["sintesi"] = testo.strip()[:6000]
    _salva(con, run)


# --- flusso API -------------------------------------------------------------


def stima(run: dict, imp: Impostazioni | None = None, prezzi: PrezziLLM | None = None) -> dict:
    imp = imp or impostazioni()
    prezzi = prezzi or prezzi_llm()
    n_seg = len(run["segmenti"]) * len(run["aree"])
    n = run["parametri"]["persone_per_segmento"]
    fattore_b = 2 if run["parametri"].get("proposta_b") else 1
    batch = n_seg > SOGLIA_BATCH
    prezzo = prezzi.modelli.get(imp.modello_simulazione)
    if prezzo is None:
        raise ErroreSimulazione(f"Prezzo mancante per {imp.modello_simulazione} in prezzi_llm.yaml")
    usd = n_seg * costo_usd(
        prezzo,
        token_input=TOKEN_ISTRUZIONI + TOKEN_CONTESTO + 200 + n * TOKEN_PER_PERSONA_IN,
        token_output=n * TOKEN_PER_PERSONA_OUT * fattore_b,
        batch=batch,
        sconto_batch=prezzi.sconto_batch,
    )
    return {"chiamate": n_seg, "batch": batch, "costo_eur": round(usd * imp.cambio_usd_eur, 4)}


def _parametri_chiamata(run: dict, area: str, indice: int) -> dict:
    con_b = bool(run["parametri"].get("proposta_b"))
    return {
        "max_tokens": 16000,
        "system": [
            {
                "type": "text",
                "text": run["parametri"]["istruzioni"],
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Contesto dell'area:\n{run['parametri']['contesti'][area]}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"{_testo_proposta(run)}\n\n{_testo_segmento(run, area, indice)}",
                    },
                ],
            }
        ],
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": ps.schema_risposta_api(con_b)},
        },
    }


def _testo_risposta(msg) -> str:
    if getattr(msg, "stop_reason", None) == "refusal":
        raise ErroreSimulazione("Il modello ha rifiutato la richiesta")
    return next((b.text for b in msg.content if b.type == "text"), "")


def _registra_testo(run: dict, area: str, indice: int, testo: str) -> None:
    dati = _estrai_json(testo)
    r = ps.RispostaSegmento.model_validate({"indice": indice, "persone": dati.get("persone", [])})
    _registra_risposta(run, area, r)


def _costo_run(con: duckdb.DuckDBPyConnection, sid: int) -> float:
    (c,) = con.execute(
        "SELECT coalesce(sum(costo_eur), 0) FROM uso_llm WHERE modulo = ?", [f"laboratorio:{sid}"]
    ).fetchone()
    return float(c)


def esegui_api(
    con: duckdb.DuckDBPyConnection,
    sid: int,
    client: ClientLLM,
    *,
    conferma: bool = False,
    imp: Impostazioni | None = None,
    prezzi: PrezziLLM | None = None,
) -> dict:
    """Esegue il run via API. Sopra la soglia di costo serve ``conferma=True``."""
    imp = imp or impostazioni()
    run = carica(con, sid)
    s = stima(run, imp, prezzi)
    if s["costo_eur"] > imp.soglia_conferma_run_eur and not conferma:
        raise RichiestaConferma(s["costo_eur"], imp.soglia_conferma_run_eur)
    client.verifica_tetto(s["costo_eur"])
    lavori = [(area, i) for area in run["aree"] for i in range(len(run["segmenti"]))]
    modulo = f"laboratorio:{sid}"
    if s["batch"]:
        richieste = [(f"{area}|{i}", _parametri_chiamata(run, area, i)) for area, i in lavori]
        batch_id = client.crea_batch(
            ruolo="simulazione", richieste=richieste, costo_previsto_eur=s["costo_eur"]
        )
        run["parametri"]["batch"] = batch_id
        _salva(con, run)
        return {"stato": "in_attesa", "batch": batch_id, **s}

    def chiama(lavoro):
        area, i = lavoro
        msg = client.messaggio(
            modulo=modulo, ruolo="simulazione", **_parametri_chiamata(run, area, i)
        )
        return area, i, _testo_risposta(msg)

    errori = []
    with ThreadPoolExecutor(max_workers=CONCORRENZA) as pool:
        for area, i, testo in pool.map(chiama, lavori):
            try:
                _registra_testo(run, area, i, testo)
            except (ErroreSimulazione, ps.ErroreRisposta, ValueError) as e:
                errori.append(f"circ. {area}, segmento {i}: {e}")
    run["costo"] = _costo_run(con, sid)
    if errori:
        run["stato"] = "errore"
        run["risultati"]["errori"] = errori
        _salva(con, run)
        return {"stato": "errore", "errori": errori, **s}
    _salva(con, run)
    completa(con, sid)
    return {"stato": "completata", **s, "costo_eur": _costo_run(con, sid)}


def raccogli_batch(con: duckdb.DuckDBPyConnection, sid: int, client: ClientLLM) -> dict:
    run = carica(con, sid)
    batch_id = run["parametri"].get("batch")
    if not batch_id:
        raise ErroreSimulazione("Questa simulazione non ha un batch in corso")
    if client.stato_batch(batch_id) != "ended":
        return {"stato": "in_attesa", "batch": batch_id}
    errori = []
    for cid, msg in client.risultati_batch(
        batch_id, modulo=f"laboratorio:{sid}", ruolo="simulazione"
    ).items():
        area, i = cid.split("|")
        try:
            if msg is None:
                raise ErroreSimulazione("richiesta non riuscita")
            _registra_testo(run, area, int(i), _testo_risposta(msg))
        except (ErroreSimulazione, ps.ErroreRisposta, ValueError) as e:
            errori.append(f"circ. {area}, segmento {i}: {e}")
    run["costo"] = _costo_run(con, sid)
    run["stato"] = "errore" if errori else run["stato"]
    if errori:
        run["risultati"]["errori"] = errori
    _salva(con, run)
    if not errori:
        completa(con, sid)
    return {"stato": "errore" if errori else "completata", "errori": errori}


def genera_sintesi_api(con: duckdb.DuckDBPyConnection, sid: int, client: ClientLLM) -> str:
    run = carica(con, sid)
    msg = client.messaggio(
        modulo=f"laboratorio:{sid}",
        ruolo="sintesi",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt_sintesi(run)}],
    )
    testo = _testo_risposta(msg)
    importa_sintesi(con, sid, testo)
    run = carica(con, sid)
    run["costo"] = _costo_run(con, sid)
    _salva(con, run)
    return testo


def richiesta_da_dict(d: dict) -> Richiesta:
    campi = {k: v for k, v in d.items() if k in Richiesta.__dataclass_fields__}
    return Richiesta(**campi)


def come_dict(r: Richiesta) -> dict:
    return asdict(r)
