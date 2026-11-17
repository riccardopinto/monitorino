"""Reddit: post e commenti recenti dei subreddit configurati, con l'API ufficiale.

Serve un'app "script" registrata su https://www.reddit.com/prefs/apps (REDDIT_CLIENT_ID e
REDDIT_CLIENT_SECRET in .env) e il rispetto dei termini della Data API di Reddit, da
verificare per l'uso da parte di una campagna. Si usa l'autenticazione application-only
(client_credentials): sola lettura di contenuti pubblici.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.temi.social.base import Connettore, ContenutoPubblico, ErroreConnettore

TOKEN = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"


class Reddit(Connettore):
    def __init__(
        self, client_id: str, segreto: str, subreddit: list[str], client: httpx.Client | None = None
    ):
        super().__init__(client)
        self.client_id = client_id
        self.segreto = segreto
        self.subreddit = subreddit
        self.nome = "Reddit " + ", ".join(f"r/{s}" for s in subreddit)

    def _token(self) -> str:
        r = self.client.post(
            TOKEN,
            auth=(self.client_id, self.segreto),
            data={"grant_type": "client_credentials"},
        )
        if r.status_code != 200:
            raise ErroreConnettore(f"Reddit: autenticazione fallita (HTTP {r.status_code})")
        return r.json()["access_token"]

    def raccogli(self, dal: datetime) -> list[ContenutoPubblico]:
        intestazioni = {"Authorization": f"Bearer {self._token()}"}
        out: list[ContenutoPubblico] = []
        for sub in self.subreddit:
            for percorso in (f"/r/{sub}/new", f"/r/{sub}/comments"):
                r = self.client.get(API + percorso, params={"limit": 100}, headers=intestazioni)
                if r.status_code != 200:
                    raise ErroreConnettore(f"Reddit {percorso}: HTTP {r.status_code}")
                for figlio in r.json().get("data", {}).get("children", []):
                    d = figlio.get("data", {})
                    quando = datetime.fromtimestamp(d.get("created_utc", 0), tz=UTC)
                    if quando < dal:
                        continue
                    # Si leggono solo i campi di testo: autore, id, permalink restano fuori.
                    testo = " ".join(
                        x for x in (d.get("title"), d.get("selftext"), d.get("body")) if x
                    )
                    c = self.contenuto(testo, quando)
                    if c:
                        out.append(c)
        return out
