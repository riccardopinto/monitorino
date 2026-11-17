"""Configurazione dell'applicazione: variabili da .env e file YAML in config/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RADICE = Path(__file__).resolve().parents[2]
DIR_CONFIG = RADICE / "config"
CIRCOSCRIZIONI = tuple(str(n) for n in range(1, 9))


class Impostazioni(BaseSettings):
    """Valori letti da .env. I nomi dei modelli non hanno default: stanno solo in .env."""

    model_config = SettingsConfigDict(
        env_file=RADICE / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: SecretStr | None = None
    modello_simulazione: str
    modello_sintesi: str
    modello_classificazione: str
    tetto_spesa_mensile_eur: float = Field(gt=0)
    soglia_conferma_run_eur: float = Field(gt=0)
    cambio_usd_eur: float = Field(gt=0, description="Euro per 1 dollaro USA")
    llm_max_retries: int = Field(default=4, ge=0)

    db_path: Path = Path("data/campagna.duckdb")

    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    youtube_api_key: SecretStr | None = None
    secret_key: SecretStr | None = None

    @field_validator("db_path")
    @classmethod
    def _percorso_assoluto(cls, valore: Path) -> Path:
        return valore if valore.is_absolute() else RADICE / valore


@lru_cache
def impostazioni() -> Impostazioni:
    return Impostazioni()


# --- File YAML --------------------------------------------------------------


class _Modello(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidato(_Modello):
    nome: str
    lista: str = ""
    ruolo: str = ""
    circoscrizione_di_riferimento: str | None = None
    tono_di_voce: str = ""
    temi_prioritari: list[str] = []
    # Una voce per posizione, con fonte. Struttura definitiva in Fase 6.
    posizioni_approvate: list[str | dict[str, Any]] = []
    da_evitare: list[str] = []
    testi_di_esempio: list[str] = []


class Candidati(_Modello):
    sindaco: Candidato
    consiglio_comunale: list[Candidato] = []
    circoscrizioni: dict[str, list[Candidato]]

    @field_validator("circoscrizioni")
    @classmethod
    def _otto_circoscrizioni(cls, valore: dict[str, list[Candidato]]) -> dict:
        if set(valore) != set(CIRCOSCRIZIONI):
            raise ValueError(f"servono esattamente le chiavi {CIRCOSCRIZIONI}")
        return valore


class SegmentoDefinizione(_Modello):
    fascia_eta: str
    condizione: str
    area_di_voto: str


class Segmenti(_Modello):
    circoscrizioni: dict[str, str]
    fasce_eta: list[str]
    condizione: list[str]
    area_di_voto: list[str]
    segmenti_default: list[SegmentoDefinizione]
    persone_per_segmento: int = Field(gt=0)

    @model_validator(mode="after")
    def _segmenti_coerenti(self) -> Segmenti:
        if set(self.circoscrizioni) != set(CIRCOSCRIZIONI):
            raise ValueError(f"servono esattamente le circoscrizioni {CIRCOSCRIZIONI}")
        for s in self.segmenti_default:
            if s.fascia_eta not in self.fasce_eta:
                raise ValueError(f"fascia d'età sconosciuta: {s.fascia_eta}")
            if s.condizione not in self.condizione:
                raise ValueError(f"condizione sconosciuta: {s.condizione}")
            if s.area_di_voto not in self.area_di_voto:
                raise ValueError(f"area di voto sconosciuta: {s.area_di_voto}")
        return self


class FonteWeb(_Modello):
    nome: str
    sito: str
    rss: str
    attiva: bool


class FonteSocial(BaseModel):
    # Ogni connettore ha parametri propri (subreddit, canali, query).
    model_config = ConfigDict(extra="allow")
    attiva: bool


class Fonti(_Modello):
    news: list[FonteWeb]
    istituzionali: list[FonteWeb]
    social: dict[str, FonteSocial]
    # Vincolo di privacy: il testo originale si cancella entro 30 giorni.
    conservazione_testi_giorni: int = Field(gt=0, le=30)


class Temi(_Modello):
    temi: list[str]

    @field_validator("temi")
    @classmethod
    def _senza_doppioni(cls, valore: list[str]) -> list[str]:
        if len(set(valore)) != len(valore):
            raise ValueError("temi duplicati")
        return valore


class PrezzoModello(_Modello):
    """USD per milione di token."""

    input: float
    output: float
    cache_lettura: float
    cache_scrittura_5m: float
    cache_scrittura_1h: float
    # Alcuni modelli hanno una tariffa più alta oltre una certa lunghezza di prompt.
    soglia_prompt_lungo: int | None = None
    input_lungo: float | None = None
    output_lungo: float | None = None


class PrezziLLM(_Modello):
    valuta: str = "USD"
    sconto_batch: float = Field(ge=0, lt=1)
    modelli: dict[str, PrezzoModello]


def _leggi_yaml(nome: str) -> dict[str, Any]:
    percorso = DIR_CONFIG / nome
    with percorso.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def candidati() -> Candidati:
    return Candidati.model_validate(_leggi_yaml("candidati.yaml"))


@lru_cache
def segmenti() -> Segmenti:
    return Segmenti.model_validate(_leggi_yaml("segmenti.yaml"))


@lru_cache
def fonti() -> Fonti:
    return Fonti.model_validate(_leggi_yaml("fonti.yaml"))


@lru_cache
def temi() -> Temi:
    return Temi.model_validate(_leggi_yaml("temi.yaml"))


@lru_cache
def prezzi_llm() -> PrezziLLM:
    return PrezziLLM.model_validate(_leggi_yaml("prezzi_llm.yaml"))
