"""Connessione DuckDB con estensione spatial e schema del database.

Uso da riga di comando: ``uv run python -m app.core.db`` crea il file e lo schema.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# Codici di sezione e circoscrizione sono sempre VARCHAR normalizzati (vedi docs/fonti_dati.md).
# Niente chiavi esterne: gli script di ingest cancellano e riscrivono intere fonti, e in DuckDB
# i vincoli FOREIGN KEY bloccherebbero quelle operazioni. Le relazioni sono indicate nei commenti.
SCHEMA = """
-- Geometrie sempre in WGS84 (EPSG:4326); i calcoli metrici si fanno in EPSG:32632.
CREATE SEQUENCE IF NOT EXISTS seq_area;
CREATE TABLE IF NOT EXISTS area (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_area'),
    tipo        VARCHAR NOT NULL
                CHECK (tipo IN ('circoscrizione', 'sezione', 'zona_statistica', 'cap')),
    codice      VARCHAR NOT NULL,
    nome        VARCHAR,
    geometria   GEOMETRY,
    id_padre    INTEGER                     -- area.id
);
-- Geometrie stimate (es. sezioni elettorali da Voronoi sui civici). Aggiunta in Fase 1.
ALTER TABLE area ADD COLUMN IF NOT EXISTS approssimata BOOLEAN DEFAULT false;

CREATE TABLE IF NOT EXISTS sezione_area (
    sezione         VARCHAR NOT NULL,
    anno            INTEGER NOT NULL,
    circoscrizione  VARCHAR NOT NULL,
    PRIMARY KEY (sezione, anno)
);

CREATE SEQUENCE IF NOT EXISTS seq_elezione;
CREATE TABLE IF NOT EXISTS elezione (
    id      INTEGER PRIMARY KEY DEFAULT nextval('seq_elezione'),
    tipo    VARCHAR NOT NULL,
    data    DATE NOT NULL,
    turno   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS affluenza (
    elezione_id     INTEGER NOT NULL,       -- elezione.id
    sezione         VARCHAR NOT NULL,
    elettori        INTEGER,
    votanti         INTEGER,
    schede_bianche  INTEGER,
    schede_nulle    INTEGER,
    PRIMARY KEY (elezione_id, sezione)
);

CREATE TABLE IF NOT EXISTS risultato (
    elezione_id     INTEGER NOT NULL,       -- elezione.id
    sezione         VARCHAR NOT NULL,
    tipo_soggetto   VARCHAR NOT NULL CHECK (tipo_soggetto IN (
                        'candidato_sindaco', 'lista', 'preferenza',
                        'presidente_circoscrizione')),
    soggetto        VARCHAR NOT NULL,
    voti            INTEGER NOT NULL CHECK (voti >= 0),
    PRIMARY KEY (elezione_id, sezione, tipo_soggetto, soggetto)
);

CREATE TABLE IF NOT EXISTS demografia (
    area_id     INTEGER NOT NULL,           -- area.id
    anno        INTEGER NOT NULL,
    variabile   VARCHAR NOT NULL,
    valore      DOUBLE,
    fonte       VARCHAR NOT NULL,
    PRIMARY KEY (area_id, anno, variabile)
);

CREATE SEQUENCE IF NOT EXISTS seq_documento;
CREATE TABLE IF NOT EXISTS documento (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_documento'),
    fonte       VARCHAR NOT NULL,
    url         VARCHAR,
    data        DATE,
    titolo      VARCHAR,
    sintesi     VARCHAR,
    testo       VARCHAR,                    -- cancellato dal job di pulizia alla scadenza
    area_id     INTEGER,                    -- area.id; NULL = livello cittadino
    tema        VARCHAR,
    sentiment   SMALLINT CHECK (sentiment BETWEEN -2 AND 2),
    scadenza    DATE
);

CREATE TABLE IF NOT EXISTS tema_aggregato (
    tema            VARCHAR NOT NULL,
    area_id         INTEGER,                -- area.id; NULL = livello cittadino
    settimana       DATE NOT NULL,          -- lunedì della settimana
    volume          INTEGER NOT NULL,
    sentiment_medio DOUBLE,
    n_fonti         INTEGER
);

CREATE SEQUENCE IF NOT EXISTS seq_segmento;
CREATE TABLE IF NOT EXISTS segmento (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_segmento'),
    definizione JSON NOT NULL               -- fascia_eta, condizione, area_di_voto
);

CREATE TABLE IF NOT EXISTS segmento_peso (
    segmento_id INTEGER NOT NULL,           -- segmento.id
    area_id     INTEGER NOT NULL,           -- area.id
    anno        INTEGER NOT NULL,
    peso        DOUBLE NOT NULL CHECK (peso BETWEEN 0 AND 1),
    PRIMARY KEY (segmento_id, area_id, anno)
);

CREATE SEQUENCE IF NOT EXISTS seq_simulazione;
CREATE TABLE IF NOT EXISTS simulazione (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_simulazione'),
    timestamp   TIMESTAMP NOT NULL DEFAULT current_timestamp,
    proposta    VARCHAR NOT NULL,
    aree        JSON,
    segmenti    JSON,
    modello     VARCHAR,
    parametri   JSON,                       -- prompt, temperatura, seed, variante A/B
    risultati   JSON,
    costo       DOUBLE                      -- EUR
);

CREATE TABLE IF NOT EXISTS calibrazione (
    simulazione_id  INTEGER NOT NULL,       -- simulazione.id
    fonte_sondaggio VARCHAR NOT NULL,
    valore_simulato DOUBLE,
    valore_reale    DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS seq_contenuto;
CREATE TABLE IF NOT EXISTS contenuto (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_contenuto'),
    candidato   VARCHAR NOT NULL,
    formato     VARCHAR NOT NULL,
    canale      VARCHAR,
    testo       VARCHAR NOT NULL,
    fonti_dati  JSON,
    stato       VARCHAR NOT NULL DEFAULT 'bozza'
                CHECK (stato IN ('bozza', 'in_revisione', 'approvato', 'scartato')),
    autore      VARCHAR,
    timestamp   TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS audit (
    utente      VARCHAR,
    azione      VARCHAR NOT NULL,
    oggetto     VARCHAR,
    timestamp   TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Registro delle chiamate LLM: alimenta il tetto di spesa e la pagina costi.
CREATE SEQUENCE IF NOT EXISTS seq_uso_llm;
CREATE TABLE IF NOT EXISTS uso_llm (
    id              INTEGER PRIMARY KEY DEFAULT nextval('seq_uso_llm'),
    timestamp       TIMESTAMP NOT NULL DEFAULT current_timestamp,
    modulo          VARCHAR NOT NULL,
    modello         VARCHAR NOT NULL,
    token_input     INTEGER NOT NULL,
    token_output    INTEGER NOT NULL,
    cache_lettura   INTEGER NOT NULL DEFAULT 0,
    cache_scrittura INTEGER NOT NULL DEFAULT 0,
    batch           BOOLEAN NOT NULL DEFAULT false,
    costo_eur       DOUBLE NOT NULL,
    utente          VARCHAR
);

-- Registro dei caricamenti: di_prova = true per i dati di data/fixtures/.
CREATE TABLE IF NOT EXISTS caricamento (
    fonte       VARCHAR NOT NULL,
    timestamp   TIMESTAMP NOT NULL DEFAULT current_timestamp,
    righe       INTEGER,
    di_prova    BOOLEAN NOT NULL
);
"""

TABELLE = (
    "area",
    "sezione_area",
    "elezione",
    "affluenza",
    "risultato",
    "demografia",
    "documento",
    "tema_aggregato",
    "segmento",
    "segmento_peso",
    "simulazione",
    "calibrazione",
    "contenuto",
    "audit",
    "uso_llm",
    "caricamento",
)


def connetti(percorso: Path | str, *, sola_lettura: bool = False) -> duckdb.DuckDBPyConnection:
    """Apre il database e carica l'estensione spatial (la installa al primo uso)."""
    if str(percorso) != ":memory:":
        Path(percorso).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(percorso), read_only=sola_lettura)
    con.install_extension("spatial")
    con.load_extension("spatial")
    return con


def crea_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Crea tabelle e sequenze mancanti. Si può rieseguire senza effetti."""
    con.execute(SCHEMA)


def tabelle_presenti(con: duckdb.DuckDBPyConnection) -> set[str]:
    righe = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {r[0] for r in righe}


def schema_completo(con: duckdb.DuckDBPyConnection) -> bool:
    return set(TABELLE) <= tabelle_presenti(con)


def dati_di_prova(con: duckdb.DuckDBPyConnection) -> bool:
    """True se nel database ci sono dati caricati da data/fixtures/."""
    return bool(con.execute("SELECT count(*) FROM caricamento WHERE di_prova").fetchone()[0])


if __name__ == "__main__":
    from app.core.config import impostazioni

    percorso = impostazioni().db_path
    with connetti(percorso) as con:
        crea_schema(con)
        print(f"Schema creato in {percorso}: {len(tabelle_presenti(con))} tabelle")
