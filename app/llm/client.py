"""Unico punto di accesso all'API Anthropic.

Ogni chiamata:
- usa il modello indicato in .env per il ruolo richiesto (mai nomi di modello nel codice);
- controlla prima il tetto di spesa mensile (TETTO_SPESA_MENSILE_EUR);
- registra token e costo stimato nella tabella uso_llm.

I tentativi su errori temporanei (429, 5xx, rete) li fa l'SDK con backoff esponenziale,
nel numero indicato da LLM_MAX_RETRIES.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

import anthropic
import duckdb
from anthropic.types import Message, Usage

from app.core.config import Impostazioni, PrezziLLM, PrezzoModello, impostazioni, prezzi_llm

Ruolo = Literal["simulazione", "sintesi", "classificazione"]


class ErroreLLM(RuntimeError):
    """Errore della chiamata all'API, con messaggio in italiano per l'interfaccia."""


class TettoSpesaSuperato(ErroreLLM):
    pass


class ModelloSenzaPrezzo(ErroreLLM):
    pass


class _SDK(Protocol):
    messages: Any


def costo_usd(
    prezzo: PrezzoModello,
    *,
    token_input: int,
    token_output: int,
    cache_lettura: int = 0,
    cache_scrittura_5m: int = 0,
    cache_scrittura_1h: int = 0,
    batch: bool = False,
    sconto_batch: float = 0.0,
) -> float:
    """Costo in USD di una chiamata, dai conteggi di token."""
    prompt_totale = token_input + cache_lettura + cache_scrittura_5m + cache_scrittura_1h
    p_input, p_output = prezzo.input, prezzo.output
    if prezzo.soglia_prompt_lungo is not None and prompt_totale > prezzo.soglia_prompt_lungo:
        p_input = prezzo.input_lungo if prezzo.input_lungo is not None else p_input
        p_output = prezzo.output_lungo if prezzo.output_lungo is not None else p_output
    costo = (
        token_input * p_input
        + token_output * p_output
        + cache_lettura * prezzo.cache_lettura
        + cache_scrittura_5m * prezzo.cache_scrittura_5m
        + cache_scrittura_1h * prezzo.cache_scrittura_1h
    ) / 1_000_000
    return costo * (1 - sconto_batch) if batch else costo


def token_da_usage(usage: Usage) -> dict[str, int]:
    """Estrae i conteggi dal campo usage di una risposta."""
    scrittura = usage.cache_creation_input_tokens or 0
    if usage.cache_creation is not None:
        scrittura_5m = usage.cache_creation.ephemeral_5m_input_tokens
        scrittura_1h = usage.cache_creation.ephemeral_1h_input_tokens
    else:
        scrittura_5m, scrittura_1h = scrittura, 0
    return {
        "token_input": usage.input_tokens,
        "token_output": usage.output_tokens,
        "cache_lettura": usage.cache_read_input_tokens or 0,
        "cache_scrittura_5m": scrittura_5m,
        "cache_scrittura_1h": scrittura_1h,
    }


class ClientLLM:
    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        *,
        imp: Impostazioni | None = None,
        prezzi: PrezziLLM | None = None,
        sdk: _SDK | None = None,
    ) -> None:
        self._con = con
        self._imp = imp or impostazioni()
        self._prezzi = prezzi or prezzi_llm()
        if sdk is None:
            chiave = self._imp.anthropic_api_key
            sdk = anthropic.Anthropic(
                api_key=chiave.get_secret_value() if chiave else None,
                max_retries=self._imp.llm_max_retries,
            )
        self._sdk = sdk

    # --- modelli e prezzi ---------------------------------------------------

    def modello(self, ruolo: Ruolo) -> str:
        return getattr(self._imp, f"modello_{ruolo}")

    def _prezzo(self, modello: str) -> PrezzoModello:
        try:
            return self._prezzi.modelli[modello]
        except KeyError:
            raise ModelloSenzaPrezzo(
                f"Il modello {modello} non ha un prezzo in config/prezzi_llm.yaml"
            ) from None

    def costo_eur(self, modello: str, *, batch: bool = False, **token: int) -> float:
        usd = costo_usd(
            self._prezzo(modello), batch=batch, sconto_batch=self._prezzi.sconto_batch, **token
        )
        return usd * self._imp.cambio_usd_eur

    def stima_eur(
        self, ruolo: Ruolo, token_input: int, token_output: int, *, batch: bool = False
    ) -> float:
        """Stima preventiva senza cache, per mostrare il costo prima di lanciare un run."""
        return self.costo_eur(
            self.modello(ruolo), batch=batch, token_input=token_input, token_output=token_output
        )

    # --- tetto di spesa -----------------------------------------------------

    def spesa_mese_eur(self) -> float:
        with self._con.cursor() as cur:
            (totale,) = cur.execute(
                "SELECT coalesce(sum(costo_eur), 0) FROM uso_llm "
                "WHERE date_trunc('month', timestamp) = date_trunc('month', current_timestamp)"
            ).fetchone()
        return float(totale)

    def verifica_tetto(self, costo_previsto_eur: float = 0.0) -> None:
        spesa = self.spesa_mese_eur()
        tetto = self._imp.tetto_spesa_mensile_eur
        if spesa >= tetto or spesa + costo_previsto_eur > tetto:
            raise TettoSpesaSuperato(
                f"Tetto di spesa mensile raggiunto: spesi {spesa:.2f} € su {tetto:.2f} €"
                + (f", previsti altri {costo_previsto_eur:.2f} €" if costo_previsto_eur else "")
            )

    # --- registro -----------------------------------------------------------

    def registra(
        self,
        *,
        modulo: str,
        modello: str,
        usage: Usage,
        batch: bool = False,
        utente: str | None = None,
    ) -> float:
        """Scrive una riga in uso_llm e restituisce il costo in euro.

        Pubblico perché lo usano anche i risultati della Batches API.
        """
        token = token_da_usage(usage)
        costo = self.costo_eur(modello, batch=batch, **token)
        with self._con.cursor() as cur:
            cur.execute(
                "INSERT INTO uso_llm (modulo, modello, token_input, token_output, "
                "cache_lettura, cache_scrittura, batch, costo_eur, utente) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    modulo,
                    modello,
                    token["token_input"],
                    token["token_output"],
                    token["cache_lettura"],
                    token["cache_scrittura_5m"] + token["cache_scrittura_1h"],
                    batch,
                    costo,
                    utente,
                ],
            )
        return costo

    # --- chiamata -----------------------------------------------------------

    def messaggio(
        self, *, modulo: str, ruolo: Ruolo, utente: str | None = None, **parametri: Any
    ) -> Message:
        """Chiama messages.create con il modello del ruolo e registra il consumo.

        ``parametri`` passa direttamente all'SDK (max_tokens, system, messages, ...).
        """
        modello = self.modello(ruolo)
        self._prezzo(modello)  # errore subito se manca il prezzo, prima di spendere
        self.verifica_tetto()
        try:
            risposta = self._sdk.messages.create(model=modello, **parametri)
        except anthropic.AuthenticationError as e:
            raise ErroreLLM("Chiave API Anthropic mancante o non valida") from e
        except anthropic.RateLimitError as e:
            raise ErroreLLM("Limite di richieste API superato, riprovare più tardi") from e
        except anthropic.BadRequestError as e:
            raise ErroreLLM(f"Richiesta non valida: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ErroreLLM(f"Errore dell'API Anthropic ({e.status_code})") from e
        except anthropic.APIConnectionError as e:
            raise ErroreLLM("API Anthropic non raggiungibile") from e
        self.registra(modulo=modulo, modello=modello, usage=risposta.usage, utente=utente)
        return risposta
