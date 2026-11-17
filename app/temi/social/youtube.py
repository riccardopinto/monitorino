"""YouTube: commenti pubblici ai video recenti dei canali di informazione locale.

Serve una chiave della YouTube Data API v3 (YOUTUBE_API_KEY in .env, da Google Cloud) e gli
id dei canali in config/fonti.yaml. Per ogni canale si leggono gli ultimi video caricati
(playlist "uploads", 1 unità di quota) e i loro commenti (commentThreads, 1 unità).
"""

from __future__ import annotations

from datetime import datetime

import httpx

from app.temi.social.base import Connettore, ContenutoPubblico, ErroreConnettore

API = "https://www.googleapis.com/youtube/v3"
VIDEO_PER_CANALE = 10


def _data(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class YouTube(Connettore):
    nome = "YouTube"

    def __init__(self, chiave: str, canali: list[str], client: httpx.Client | None = None):
        super().__init__(client)
        self.chiave = chiave
        self.canali = canali

    def _get(self, risorsa: str, **parametri) -> dict:
        r = self.client.get(f"{API}/{risorsa}", params={"key": self.chiave, **parametri})
        if r.status_code != 200:
            raise ErroreConnettore(f"YouTube {risorsa}: HTTP {r.status_code}")
        return r.json()

    def raccogli(self, dal: datetime) -> list[ContenutoPubblico]:
        out: list[ContenutoPubblico] = []
        for canale in self.canali:
            info = self._get("channels", part="contentDetails", id=canale)
            if not info.get("items"):
                continue
            uploads = info["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            video = self._get(
                "playlistItems",
                part="contentDetails",
                playlistId=uploads,
                maxResults=VIDEO_PER_CANALE,
            )
            for v in video.get("items", []):
                id_video = v["contentDetails"]["videoId"]  # usato solo per la richiesta
                commenti = self._get(
                    "commentThreads", part="snippet", videoId=id_video, maxResults=100, order="time"
                )
                for c in commenti.get("items", []):
                    s = c["snippet"]["topLevelComment"]["snippet"]
                    quando = _data(s["publishedAt"])
                    if quando < dal:
                        continue
                    # Solo testo e data: nome e canale dell'autore restano fuori.
                    contenuto = self.contenuto(s.get("textOriginal"), quando)
                    if contenuto:
                        out.append(contenuto)
        return out
