"""Connettori social. Si attivano in config/fonti.yaml e con le credenziali in .env."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb

from app.core.config import Impostazioni, fonti, impostazioni
from app.ingest._comune import registra_caricamento
from app.temi.social.base import Connettore, scrivi
from app.temi.social.bluesky import Bluesky
from app.temi.social.reddit import Reddit
from app.temi.social.youtube import YouTube


def _segreto(valore) -> str | None:
    return valore.get_secret_value() if valore else None


def connettori_attivi(imp: Impostazioni | None = None) -> tuple[list[Connettore], list[str]]:
    """Connettori attivi in fonti.yaml e con credenziali; più l'elenco dei motivi di esclusione."""
    imp = imp or impostazioni()
    social = fonti().social
    attivi: list[Connettore] = []
    note: list[str] = []
    cfg = social.get("reddit")
    if cfg and cfg.attiva:
        if imp.reddit_client_id and imp.reddit_client_secret:
            attivi.append(
                Reddit(
                    _segreto(imp.reddit_client_id),
                    _segreto(imp.reddit_client_secret),
                    list(getattr(cfg, "subreddit", []) or []),
                )
            )
        else:
            note.append("Reddit attivo ma senza REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET")
    cfg = social.get("youtube")
    if cfg and cfg.attiva:
        canali = list(getattr(cfg, "canali", []) or [])
        if imp.youtube_api_key and canali:
            attivi.append(YouTube(_segreto(imp.youtube_api_key), canali))
        else:
            note.append("YouTube attivo ma senza YOUTUBE_API_KEY o senza canali")
    cfg = social.get("bluesky")
    if cfg and cfg.attiva:
        if imp.bluesky_handle and imp.bluesky_app_password:
            attivi.append(
                Bluesky(
                    imp.bluesky_handle,
                    _segreto(imp.bluesky_app_password),
                    list(getattr(cfg, "query", []) or []),
                )
            )
        else:
            note.append("Bluesky attivo ma senza BLUESKY_HANDLE/BLUESKY_APP_PASSWORD")
    return attivi, note


def raccogli(con: duckdb.DuckDBPyConnection, giorni_indietro: int = 2) -> dict[str, str]:
    dal = datetime.now(UTC) - timedelta(days=giorni_indietro)
    giorni = fonti().conservazione_testi_giorni
    attivi, note = connettori_attivi()
    esiti = {f"nota {i + 1}": n for i, n in enumerate(note)}
    if not attivi and not note:
        esiti["social"] = "nessun connettore attivo in config/fonti.yaml"
    totale = 0
    for c in attivi:
        try:
            contenuti = c.raccogli(dal)
            n = scrivi(con, c.nome, contenuti, giorni)
            totale += n
            esiti[c.nome] = f"{len(contenuti)} contenuti, {n} nuovi"
        except Exception as e:  # noqa: BLE001 - un connettore che fallisce non ferma gli altri
            esiti[c.nome] = f"ERRORE: {e}"
    registra_caricamento(con, "social", totale)
    return esiti
