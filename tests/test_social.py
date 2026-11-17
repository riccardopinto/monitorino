"""Connettori social con risposte finte: nel risultato non deve restare nessun identificativo."""

import json
import re
from datetime import UTC, date, datetime

import httpx

from app.core import db
from app.temi.social import base
from app.temi.social.bluesky import Bluesky
from app.temi.social.reddit import Reddit
from app.temi.social.youtube import YouTube

DAL = datetime(2026, 11, 1, tzinfo=UTC)
RECENTE = datetime(2026, 11, 15, 10, tzinfo=UTC)
VECCHIO = datetime(2026, 10, 1, tzinfo=UTC)

# Identificativi che compaiono nelle risposte finte e non devono sopravvivere.
VIETATI = [
    "mario_rossi", "t3_abc123", "UCcanale", "did:plc:", "at://", "bsky.app/profile",
    "reddit.com", "youtube.com", "@", "u/", "anna.bsky.social", "mail@esempio.it",
]  # fmt: skip


def _controlla(contenuti):
    assert contenuti, "nessun contenuto raccolto"
    for c in contenuti:
        assert set(vars(c)) == {"testo", "data"}
        for v in VIETATI:
            assert v not in c.testo, (v, c.testo)


def test_anonimizza():
    t = base.anonimizza(
        "Ciao @anna.bsky.social e u/mario_rossi, guarda https://reddit.com/x o scrivi a "
        "mail@esempio.it per il parco di via Roma"
    )
    assert t == "Ciao e , guarda o scrivi a per il parco di via Roma"


def test_reddit():
    def risposta(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "tok"})
        assert req.headers["Authorization"] == "Bearer tok"
        figli = [
            {"data": {"title": "Cantiere in corso Francia, traffico bloccato da giorni",
                      "selftext": "Lo dice anche u/mario_rossi https://reddit.com/r/torino/x",
                      "author": "mario_rossi", "id": "t3_abc123", "permalink": "/r/torino/abc",
                      "created_utc": RECENTE.timestamp()}},
            {"data": {"body": "Commento vecchio sulla ZTL di Torino centro storico",
                      "author": "x", "created_utc": VECCHIO.timestamp()}},
        ]  # fmt: skip
        return httpx.Response(200, json={"data": {"children": figli}})

    client = httpx.Client(transport=httpx.MockTransport(risposta))
    c = Reddit("id", "segreto", ["torino"], client=client).raccogli(DAL)
    _controlla(c)
    assert len(c) == 2  # un post da /new e uno da /comments (stessa risposta finta)
    assert c[0].testo.startswith("Cantiere in corso Francia")
    assert c[0].data == date(2026, 11, 15)


def test_youtube():
    def risposta(req: httpx.Request) -> httpx.Response:
        risorsa = req.url.path.rsplit("/", 1)[-1]
        if risorsa == "channels":
            dati = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUlista"}}}]}
        elif risorsa == "playlistItems":
            dati = {"items": [{"contentDetails": {"videoId": "vid1"}}]}
        else:
            snippet = {
                "textOriginal": "Servizio sui mercati di Porta Palazzo, @mario_rossi dice il vero",
                "authorDisplayName": "Mario Rossi",
                "authorChannelUrl": "https://youtube.com/UCcanale",
                "publishedAt": "2026-11-15T10:00:00Z",
            }
            dati = {"items": [{"snippet": {"topLevelComment": {"snippet": snippet}}}]}
        return httpx.Response(200, json=dati)

    client = httpx.Client(transport=httpx.MockTransport(risposta))
    c = YouTube("chiave", ["UCcanale"], client=client).raccogli(DAL)
    _controlla(c)
    assert "Porta Palazzo" in c[0].testo


def test_bluesky():
    def risposta(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("createSession"):
            assert json.loads(req.content)["identifier"] == "staff.bsky.social"
            return httpx.Response(200, json={"accessJwt": "jwt"})
        post = {
            "uri": "at://did:plc:xyz/app.bsky.feed.post/1",
            "author": {"did": "did:plc:xyz", "handle": "anna.bsky.social"},
            "record": {
                "text": "La linea 2 della metro di Torino quando arriva? cc @anna.bsky.social",
                "createdAt": "2026-11-15T10:00:00.000Z",
            },
        }
        return httpx.Response(200, json={"posts": [post]})

    client = httpx.Client(transport=httpx.MockTransport(risposta))
    c = Bluesky("staff.bsky.social", "pw", ["torino"], client=client).raccogli(DAL)
    _controlla(c)


def test_scrittura_senza_url_e_con_scadenza(tmp_path):
    con = db.connetti(tmp_path / "s.duckdb")
    db.crea_schema(con)
    contenuti = [
        base.ContenutoPubblico("Testo pubblico sul verde di Torino nord", date(2026, 11, 15))
    ]
    assert base.scrivi(con, "Bluesky", contenuti, 30) == 1
    assert base.scrivi(con, "Bluesky", contenuti, 30) == 0
    url, tipo, scadenza = con.execute("SELECT url, tipo_fonte, scadenza FROM documento").fetchone()
    assert url is None and tipo == "social"
    assert (scadenza - date.today()).days == 30
    con.close()


def test_testi_corti_scartati():
    assert base.Connettore.contenuto("@utente ok", RECENTE) is None


def test_nessun_identificativo_nel_database_reale():
    """Scansione del database reale: nessun identificativo nei documenti social."""
    import pytest

    from app.core.config import impostazioni

    try:
        con = db.connetti(impostazioni().db_path, sola_lettura=True)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database reale non disponibile: {e}")
    righe = con.execute(
        "SELECT url, coalesce(testo, '') || ' ' || coalesce(sintesi, '') || ' ' || "
        "coalesce(titolo, '') FROM documento WHERE tipo_fonte = 'social'"
    ).fetchall()
    con.close()
    schema = re.compile(r"(?<![\w])@[\w.\-]+|(?<![\w])/?u/[\w\-]+|https?://|did:plc:|at://")
    for url, testo in righe:
        assert url is None
        assert not schema.search(testo), testo
