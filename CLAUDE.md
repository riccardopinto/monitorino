# CLAUDE.md

Questo file descrive il progetto a Claude Code. Leggilo per intero prima di ogni sessione di lavoro.

## Il progetto

Piattaforma interna di analisi e comunicazione per le elezioni comunali di Torino previste nella primavera 2027. Supporta la candidatura a sindaco di Guido Saracco, la candidatura al Consiglio comunale di Francesco Aglieri Rinella e i candidati ai consigli delle 8 circoscrizioni. L'elenco aggiornato dei candidati e le loro posizioni ufficiali stanno in `config/candidati.yaml`.

Gli utenti sono poche persone dello staff di campagna. L'applicazione gira in locale o su un server privato con login. Non è un prodotto pubblico.

Il piano di sviluppo, diviso in fasi con i prompt da usare, è in `docs/FASI.md`.

## Moduli

1. Mappa. Torino divisa nelle 8 circoscrizioni, con dettaglio opzionale per sezione elettorale. Ogni altro modulo lavora sull'area selezionata in mappa.
2. Storico elettorale. Risultati per sezione e per circoscrizione di comunali 2016 e 2021 (sindaco, liste, preferenze, consigli circoscrizionali), politiche 2022, europee 2019 e 2024, regionali 2024. Affluenza, spostamenti di voto tra elezioni, confronto tra due aree o tra due elezioni.
3. Demografia. Popolazione per circoscrizione (età, sesso, cittadinanza, famiglie), istruzione e occupazione dal censimento ISTAT, reddito IRPEF per CAP dove disponibile.
4. Temi. Argomenti più discussi per circoscrizione e a livello cittadino, da news locali e da fonti social pubbliche, conservati solo in forma aggregata.
5. Laboratorio messaggi. Simula con un LLM la reazione di segmenti di elettorato a una proposta e restituisce i risultati divisi per profilo elettorale e per area.
6. Studio contenuti. Genera bozze di messaggi (post, volantini, testi per comizi, comunicati) per ciascun candidato, con approvazione umana prima dell'uso.
7. Report. Ogni vista e ogni simulazione si esporta in PDF da condividere.

## Stack

- Python 3.12, FastAPI, `uv` per dipendenze e ambiente.
- DuckDB con estensione `spatial` come database unico (`data/campagna.duckdb`).
- geopandas e shapely per le geometrie. Il frontend riceve GeoJSON semplificato.
- Frontend senza build step: HTML servito da FastAPI, Leaflet per la mappa, Chart.js per i grafici, Alpine.js per lo stato dell'interfaccia. File statici in `web/static/`.
- LLM: SDK Python di Anthropic. I nomi dei modelli stanno in `.env` (vedi `.env.example`), mai scritti nel codice.
- PDF: template Jinja2 in HTML stampati con Playwright (Chromium headless). Le mappe dei report sono immagini statiche generate lato server con geopandas e matplotlib, così il PDF esce sempre uguale.
- Raccolte periodiche (news, social): APScheduler dentro l'app, con ogni job lanciabile anche da riga di comando.
- Test con pytest, lint con ruff.

## Struttura

```
app/
  main.py
  api/            router FastAPI, uno per modulo
  core/           config, connessione db, auth, logging, budget API
  ingest/         uno script per fonte dati
  analysis/       elezioni, demografia, temi, flussi
  llm/            client, prompt, persone sintetiche, simulazione, generazione
  reports/        template Jinja2 e generatore PDF
web/
  index.html
  static/js/  static/css/
config/
  candidati.yaml  segmenti.yaml  fonti.yaml  temi.yaml
data/
  raw/<fonte>/<data>/   download originali, mai modificati
  processed/
  fixtures/             dati di prova, sempre etichettati come tali
docs/
  FASI.md  fonti_dati.md  privacy.md  metodo_simulazione.md
tests/
```

## Modello dati

- `area`: id, tipo (circoscrizione, sezione, zona_statistica, cap), codice, nome, geometria, id_padre
- `sezione_area`: sezione, anno, circoscrizione. Le sezioni elettorali cambiano nel tempo, quindi la corrispondenza va tenuta per anno.
- `elezione`: id, tipo, data, turno
- `affluenza`: elezione_id, sezione, elettori, votanti, schede bianche, nulle
- `risultato`: elezione_id, sezione, tipo_soggetto (candidato_sindaco, lista, preferenza, presidente_circoscrizione), soggetto, voti
- `demografia`: area_id, anno, variabile, valore, fonte
- `documento`: id, fonte, url, data, titolo, sintesi, area_id (nullable), tema, sentiment, scadenza
- `tema_aggregato`: tema, area_id, settimana, volume, sentiment_medio, n_fonti
- `segmento`: id, definizione, peso per area
- `simulazione`: id, timestamp, proposta, aree, segmenti, modello, parametri, risultati (JSON), costo
- `calibrazione`: simulazione_id, fonte_sondaggio, valore_simulato, valore_reale
- `contenuto`: id, candidato, formato, canale, testo, fonti_dati, stato (bozza, in_revisione, approvato, scartato), autore, timestamp
- `audit`: utente, azione, oggetto, timestamp

## Regole di lavoro

- Prima di ogni fase usa plan mode, mostrami il piano e aspetta conferma.
- Un commit per passo concluso, con messaggio in italiano.
- Ogni fonte ha uno script in `app/ingest/` idempotente: scarica in `data/raw/`, valida, scrive in DuckDB. Registra in `docs/fonti_dati.md` URL, data di download, licenza e note sul formato.
- Non inventare dati. Se un dataset non si trova, ha cambiato formato o richiede una registrazione, fermati e chiedimi. Per sviluppare senza dati reali usa `data/fixtures/`, e la dashboard deve mostrare l'etichetta "DATI DI PROVA" finché quei dati sono caricati.
- Codici di sezione e circoscrizione sempre come stringhe normalizzate. La regola va scritta in `docs/fonti_dati.md`.
- Test obbligatori per parser e aggregazioni. Controllo minimo: la somma dei voti per circoscrizione deve coincidere con i totali ufficiali pubblicati dal Comune o da Eligendo.
- Interfaccia e report in italiano.
- Le chiamate all'API Anthropic passano tutte da `app/llm/client.py`, che registra token, costo stimato e rispetta il tetto di spesa in `.env`.

## Vincoli legali e di privacy

Le opinioni politiche sono dati di categoria particolare (art. 9 GDPR). Dal 10 ottobre 2025 si applica il Regolamento UE 2024/900 sulla trasparenza e il targeting della pubblicità politica, che riguarda anche agenzie e consulenti. Si applicano anche la legge 28/2000 sulla par condicio e i termini d'uso delle piattaforme. Queste regole non si aggirano per comodità di sviluppo:

- Nessun profilo di singoli elettori. L'unità minima di analisi è la sezione elettorale o l'area statistica.
- Social: solo contenuti pubblici, raccolti con API ufficiali o da fonti che lo permettono. Niente scraping di gruppi chiusi o di piattaforme che lo vietano. Non si salvano nomi utente, ID, foto o link ai profili. Il testo originale serve solo a estrarre tema, sentiment e area, poi si cancella entro 30 giorni (campo `scadenza`, job di pulizia).
- I segmenti del laboratorio messaggi descrivono gruppi aggregati e servono a scrivere messaggi migliori. Non devono diventare liste di destinatari per annunci: il targeting online di annunci politici sotto il Regolamento 2024/900 richiede consenso esplicito e dati forniti dall'interessato.
- Contenuti generati: niente citazioni inventate attribuite a persone reali, niente affermazioni sugli avversari senza una fonte verificabile collegata, niente immagini o voci sintetiche di persone reali. Ogni dato numerico in una bozza deve rimandare a una riga del database o a una fonte esterna citata. Ogni bozza resta in stato `bozza` finché un utente non la approva.
- Ogni risultato del laboratorio messaggi riporta la dicitura "Simulazione IA, non è un sondaggio".
- `docs/privacy.md` elenca trattamenti, basi giuridiche, tempi di conservazione e misure di sicurezza. Va aggiornato a ogni fase: servirà alla valutazione d'impatto (DPIA) da far verificare a un consulente legale.

## Metodo del laboratorio messaggi

- Il panel nasce da `config/segmenti.yaml`: incroci di circoscrizione, fascia d'età, condizione (studente, lavoratore dipendente, autonomo, pensionato, in cerca di lavoro) e area di voto stimata (centrosinistra, centrodestra, M5S, civici, astensione). I pesi per area vengono dai dati reali di demografia e voto.
- Una chiamata per segmento restituisce in JSON un gruppo di persone sintetiche (default 10), ognuna con: gradimento da 1 a 5, effetto sul voto (allontana, nessuno, avvicina), timori, parole ricordate, una frase di reazione.
- Il prompt di ogni segmento include il contesto dell'area: temi caldi dal modulo 4, dati demografici, risultati elettorali passati. Il contesto comune usa il prompt caching.
- Aggregazione pesata per segmento e per area, con dispersione e obiezioni ricorrenti raggruppate.
- Ogni run salva proposta, prompt, modello, temperatura e seed, così due versioni dello stesso messaggio si confrontano (test A/B).
- Calibrazione: quando escono sondaggi reali su un tema, confronta le stime e registra lo scarto in `calibrazione`. La UI mostra un indice di affidabilità basato su questi scarti.
- Limiti da dichiarare in ogni report di simulazione: gli LLM tendono a risposte moderate e prevedibili, sottostimano l'astensione e conoscono poco la cronaca locale recente.
- Inferenza ecologica: i dati demografici descrivono i residenti di un'area, non chi ha votato. Una correlazione tra area e voto non dice nulla sul comportamento delle singole persone, e i testi della dashboard devono rispettare questa distinzione.

## Comandi

```
uv run fastapi dev app/main.py        # avvio in sviluppo
uv run python -m app.ingest.<fonte>   # ingest di una fonte
uv run pytest
uv run ruff check . && uv run ruff format .
```
