"""Bluesky: ricerca di post pubblici in italiano per parole chiave.

La ricerca pubblica senza autenticazione non è più disponibile (verificato il 2026-11-17):
serve un account dello staff con una "app password" (BLUESKY_HANDLE e BLUESKY_APP_PASSWORD
in .env). Si legge solo il testo dei post; autore e identificativi restano fuori.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from app.temi.social.base import Connettore, ContenutoPubblico, ErroreConnettore

PDS = "https://bsky.social/xrpc"


class Bluesky(Connettore):
    nome = "Bluesky"

    def __init__(
        self, handle: str, password: str, query: list[str], client: httpx.Client | None = None
    ):
        super().__init__(client)
        self.handle = handle
        self.password = password
        self.query = query

    def _sessione(self) -> str:
        r = self.client.post(
            f"{PDS}/com.atproto.server.createSession",
            json={"identifier": self.handle, "password": self.password},
        )
        if r.status_code != 200:
            raise ErroreConnettore(f"Bluesky: accesso fallito (HTTP {r.status_code})")
        return r.json()["accessJwt"]

    def raccogli(self, dal: datetime) -> list[ContenutoPubblico]:
        intestazioni = {"Authorization": f"Bearer {self._sessione()}"}
        out: list[ContenutoPubblico] = []
        for q in self.query:
            r = self.client.get(
                f"{PDS}/app.bsky.feed.searchPosts",
                params={"q": q, "lang": "it", "since": dal.isoformat(), "limit": 100},
                headers=intestazioni,
            )
            if r.status_code != 200:
                raise ErroreConnettore(f"Bluesky searchPosts: HTTP {r.status_code}")
            for post in r.json().get("posts", []):
                record = post.get("record", {})
                creato = record.get("createdAt")
                if not creato:
                    continue
                quando = datetime.fromisoformat(creato.replace("Z", "+00:00"))
                if quando < dal:
                    continue
                c = self.contenuto(record.get("text"), quando)
                if c:
                    out.append(c)
        return out
