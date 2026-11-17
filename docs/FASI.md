# Piano di sviluppo per fasi

Ogni fase ha un prompt da incollare in Claude Code e i criteri per considerarla chiusa. Procedi in ordine: le fasi successive usano tabelle e componenti delle precedenti. Avvia ogni fase in plan mode (Shift+Tab due volte) e approva il piano prima di lasciare scrivere codice.

---

## Fase 0. Impianto del progetto

Prompt:

```
Leggi CLAUDE.md e docs/FASI.md. Crea l'impianto del progetto:
- pyproject.toml gestito con uv, dipendenze di base (fastapi, uvicorn, duckdb, geopandas,
  shapely, pandas, httpx, jinja2, pydantic-settings, pyyaml, anthropic, apscheduler,
  playwright, matplotlib, pytest, ruff)
- la struttura di cartelle descritta in CLAUDE.md
- app/core/config.py che legge .env e i file in config/
- app/core/db.py con connessione DuckDB, caricamento estensione spatial e creazione
  dello schema descritto nella sezione "Modello dati"
- app/llm/client.py: wrapper dell'SDK Anthropic con log di token e costo stimato,
  tetto di spesa mensile da .env, retry con backoff
- una pagina web/index.html vuota con layout a tre zone (barra laterale filtri, mappa
  al centro, pannello dettagli a destra) e menu per i moduli
- docs/fonti_dati.md e docs/privacy.md con lo scheletro delle sezioni
- un test che verifica la creazione dello schema
Non scaricare ancora dati.
```

Chiusura: `uv run fastapi dev app/main.py` apre la pagina vuota, `uv run pytest` passa, lo schema esiste nel file DuckDB.

---

## Fase 1. Mappa e geodati

Prompt:

```
Implementa il modulo mappa.
1. Scrivi app/ingest/geodati.py che scarica dal geoportale del Comune di Torino il
   dataset "Azzonamenti Statistici - Circoscrizioni" (shapefile o GeoJSON, sistema di
   riferimento da verificare) e lo carica nella tabella area con tipo circoscrizione.
2. Cerca nel geoportale e su aperto.comune.torino.it le geometrie delle sezioni
   elettorali. Se esistono, caricale con tipo sezione. Se non esistono, usa il dataset
   "Associazione indirizzi e seggi elettorali" (civico -> sezione) e proponimi un
   metodo per costruire poligoni approssimati (per esempio Voronoi sui civici
   geocodificati, ritagliati sul confine comunale). Chiedimi conferma prima di
   procedere con l'approssimazione.
3. Popola sezione_area con la circoscrizione di ogni sezione per ogni anno disponibile.
4. Endpoint /api/aree?tipo=... che restituisce GeoJSON semplificato in WGS84.
5. Nel frontend: mappa Leaflet centrata su Torino, livello circoscrizioni con nome e
   numero, interruttore per il livello sezioni, clic su un'area che la seleziona e
   aggiorna il pannello dettagli. Lo stato della selezione va in un oggetto Alpine
   condiviso da tutti i moduli.
6. Documenta fonti e licenze in docs/fonti_dati.md.
```

Chiusura: le 8 circoscrizioni compaiono con i nomi corretti; il livello sezioni si accende e si spegne; ogni sezione ha una circoscrizione assegnata.

---

## Fase 2. Storico elettorale

Prompt:

```
Implementa il modulo storico elettorale.
1. Individua le fonti con dati per sezione per queste consultazioni a Torino:
   comunali 2016 e 2021 (primo turno e ballottaggio, sindaco, liste, preferenze,
   consigli di circoscrizione), politiche 2022, europee 2019 e 2024, regionali 2024.
   Parti da aperto.comune.torino.it e dall'archivio elettorale del Comune. Usa
   Eligendo (Ministero dell'Interno) per i totali di controllo. Presentami una tabella
   fonte per fonte con formato e copertura prima di scrivere gli script.
2. Uno script di ingest per consultazione, che riempie elezione, affluenza, risultato.
   Normalizza i nomi delle liste in una tabella di alias, così la stessa forza
   politica si confronta tra elezioni diverse; aggiungi una colonna "area politica"
   (centrosinistra, centrodestra, M5S, civici, altro) che io posso correggere a mano
   in config/aree_politiche.yaml.
3. Test: per ogni consultazione, somma per comune uguale al totale ufficiale.
4. app/analysis/elezioni.py: aggregazione per circoscrizione, affluenza, quote per
   lista e per area politica, variazione tra due elezioni, stima dei flussi tra
   elezioni a livello di sezione (regressione ecologica di Goodman con vincoli, o
   metodo equivalente che mi proponi). I flussi vanno sempre etichettati come stima.
5. Frontend:
   - mappa coropletica con selettori per elezione, turno, soggetto (lista, area
     politica, candidato) e metrica (quota, voti assoluti, affluenza, variazione)
   - pannello dettagli con grafico a barre dei risultati dell'area selezionata e
     confronto con la media cittadina
   - modalità confronto: due aree affiancate oppure la stessa area in due elezioni
   - tabella dei flussi stimati per l'area selezionata
```

Chiusura: i totali coincidono con le fonti ufficiali; la mappa mostra il risultato 2021 di ogni candidato sindaco per circoscrizione e sezione; il confronto 2021 contro europee 2024 funziona.

---

## Fase 3. Demografia

Prompt:

```
Implementa il modulo demografia.
1. Fonti da verificare e caricare:
   - Ufficio di statistica del Comune di Torino: popolazione residente per
     circoscrizione (età, sesso, cittadinanza, famiglie), serie annuali recenti
   - ISTAT, basi territoriali e variabili censuarie per sezione di censimento
     (istruzione, occupazione, abitazioni), da aggregare sulle circoscrizioni e,
     dove possibile, sulle sezioni elettorali tramite intersezione geometrica
   - Dipartimento delle Finanze, redditi IRPEF per CAP, se disponibili per Torino;
     ripartizione sulle aree pesata per popolazione
   Mostrami cosa hai trovato prima di scrivere gli script.
2. Ingest nella tabella demografia con variabile, valore, anno, fonte.
3. Indicatori derivati: indice di vecchiaia, quota stranieri, quota laureati, tasso
   di occupazione, reddito medio dichiarato, dimensione media delle famiglie.
4. Frontend:
   - livello coropletico demografico selezionabile come per le elezioni
   - scheda profilo dell'area selezionata con piramide d'età e indicatori a confronto
     con la media cittadina
   - grafico a dispersione indicatore demografico contro risultato elettorale, per
     sezione o circoscrizione, con la nota sull'inferenza ecologica sempre visibile
5. Calcola i pesi dei segmenti di config/segmenti.yaml per ogni circoscrizione e
   salvali nella tabella segmento: serviranno al laboratorio messaggi.
```

Chiusura: ogni circoscrizione ha una scheda demografica completa con fonte e anno; i pesi dei segmenti sommano a 1 per area.

---

## Fase 4. Temi caldi da news e social

Prompt:

```
Implementa il modulo temi.
1. config/fonti.yaml contiene le fonti. Verifica gli URL dei feed RSS delle testate
   locali e delle pagine istituzionali (comunicati del Comune, ordini del giorno dei
   consigli di circoscrizione) e segnalami quelli non funzionanti.
2. Raccolta news: job giornaliero che legge i feed, salva in documento titolo, URL,
   data e una sintesi breve. Non salvare il testo integrale degli articoli.
3. Raccolta social, solo da fonti pubbliche e con API ufficiali. Per ogni connettore
   crea una classe con la stessa interfaccia, attivabile da fonti.yaml:
   - Reddit (subreddit di Torino) tramite API ufficiale
   - commenti YouTube sui canali di informazione locale tramite YouTube Data API
   - Bluesky tramite API pubblica
   - altre piattaforme solo se esiste un accesso consentito: chiedimi prima
   Al momento della raccolta scarta autore, ID e link al profilo. Imposta la scadenza
   del testo a 30 giorni e scrivi il job di pulizia.
4. Geolocalizzazione: costruisci un dizionario di vie, quartieri, piazze, mercati,
   scuole e luoghi noti associati a una circoscrizione (partendo dai dati
   toponomastici del Comune). Assegna ogni documento a un'area se il testo ne cita
   una, altrimenti livello cittadino.
5. Classificazione con LLM in batch (Message Batches API): tema dalla tassonomia di
   config/temi.yaml, sentiment da -2 a +2, area se il dizionario non l'ha trovata.
6. Aggregazione settimanale in tema_aggregato.
7. Frontend:
   - matrice temi per circoscrizione colorata per volume, con sentiment medio
   - andamento nel tempo dei primi temi per l'area selezionata
   - elenco degli articoli più recenti per tema e area (titolo, testata, data, link)
   - per i social solo numeri aggregati e frasi riassuntive, mai post singoli
```

Chiusura: dopo una settimana di raccolta la matrice è popolata; nessun dato identificativo di utenti social nel database (aggiungi un test che lo verifica).

---

## Fase 5. Laboratorio messaggi

Prompt:

```
Implementa il laboratorio messaggi seguendo la sezione "Metodo del laboratorio
messaggi" di CLAUDE.md. Scrivi prima docs/metodo_simulazione.md con il metodo in
chiaro e mostramelo.
1. Input dalla UI: testo della proposta, candidato che la presenta, aree (una
   circoscrizione, più circoscrizioni o tutta la città), segmenti da includere,
   numero di persone sintetiche per segmento, variante A/B opzionale.
2. Costruzione del contesto per ogni area: dati demografici, risultati 2021 e
   recenti, temi caldi delle ultime 4 settimane. Il contesto va in un blocco
   cacheato del prompt.
3. Una chiamata per segmento e area, output JSON validato con pydantic. Le chiamate
   vanno in parallelo con un limite di concorrenza; per run grandi usa la Batches API.
   Stima del costo mostrata prima di lanciare, conferma richiesta sopra una soglia.
4. Aggregazione: gradimento medio pesato, percentuali allontana/nessuno/avvicina,
   dispersione, obiezioni raggruppate per somiglianza, frasi di reazione
   rappresentative. Una sintesi finale scritta dal modello di sintesi con: chi
   apprezza, chi si oppone e perché, rischi, suggerimenti di riformulazione.
5. Frontend:
   - form della proposta e scelta dei segmenti
   - risultati per segmento (barre divergenti) e per area (mappa colorata sul
     gradimento netto)
   - confronto A/B affiancato
   - dicitura fissa "Simulazione IA, non è un sondaggio" e indice di affidabilità
     dalla tabella calibrazione
6. Pagina per inserire a mano i risultati di sondaggi reali e collegarli a una
   simulazione per la calibrazione.
Usa come casi di test: "un nuovo parco nella circoscrizione 3" e "regole più rigide
sul centro sociale Askatasuna" valutato sull'elettorato potenziale del candidato.
```

Chiusura: i due casi di test producono risultati diversi e spiegabili per segmento; ogni run è salvata e ripetibile con lo stesso seed; il costo di ogni run è registrato.

---

## Fase 6. Studio contenuti

Prompt:

```
Implementa lo studio contenuti.
1. Leggi config/candidati.yaml: per ogni candidato tono di voce, temi prioritari,
   posizioni approvate, cose da evitare, esempi di testi già pubblicati. Il generatore
   può usare solo posizioni presenti in posizioni_approvate; se la richiesta ne
   richiede una nuova, lo segnala invece di inventarla.
2. Formati: post Instagram, post Facebook, thread, testo per volantino, SMS o
   messaggio WhatsApp per i volontari, comunicato stampa, scaletta per un intervento
   di 3 minuti. Limiti di lunghezza per formato in config.
3. Input: candidato, formato, tema, area, segmento destinatario, eventuale
   simulazione collegata (per riusare obiezioni e riformulazioni suggerite).
4. Ogni numero o fatto nella bozza deve avere una fonte collegata (riga del
   database o URL). Un controllo automatico segnala le frasi con dati senza fonte.
5. Controllo stile: niente citazioni attribuite a persone reali che non siano nel
   materiale fornito, niente affermazioni sugli avversari senza fonte.
6. Flusso di stato bozza, in_revisione, approvato, scartato, con autore e data.
   Se il contenuto sarà usato come annuncio a pagamento, la UI aggiunge il promemoria
   sugli obblighi di etichettatura e trasparenza del Regolamento UE 2024/900.
7. Frontend: editor con generazione di 3 varianti, modifica manuale, confronto,
   archivio filtrabile per candidato, stato e tema, copia rapida del testo.
```

Chiusura: una bozza generata per Saracco e una per Aglieri Rinella rispettano tono e posizioni del file di configurazione; le frasi con dati senza fonte vengono segnalate.

---

## Fase 7. Report PDF

Prompt:

```
Implementa la generazione di report PDF con template Jinja2 e Playwright.
Tipi di report:
- scheda circoscrizione: mappa, profilo demografico, storico elettorale, temi caldi
- confronto tra elezioni o tra aree
- bollettino settimanale dei temi
- report di simulazione: proposta, metodo in breve, risultati per segmento e area,
  sintesi, limiti, dicitura "Simulazione IA, non è un sondaggio"
- kit messaggi di un candidato: contenuti approvati di un periodo
Ogni report ha copertina con titolo, data e autore, piè di pagina con numero di
pagina, sezione finale con fonti e date dei dati. Le mappe sono immagini statiche
generate lato server. I grafici si renderizzano nella pagina prima della stampa
(attendi l'evento di fine rendering).
Nella dashboard ogni vista ha un pulsante "Esporta PDF" che apre un'anteprima con
le opzioni del report. I PDF generati vanno in un archivio consultabile.
```

Chiusura: ogni tipo di report si genera in meno di 30 secondi, con mappe e grafici leggibili in stampa A4.

---

## Fase 8. Sicurezza e messa in produzione

Prompt:

```
Prepara l'applicazione per l'uso da parte dello staff.
1. Login con utenti in database, password con hash argon2, sessioni con cookie
   sicuri. Ruoli: admin, analista, comunicazione. Solo admin gestisce utenti e fonti.
2. Tabella audit per ogni simulazione, generazione, approvazione ed export.
3. Pagina costi API con consumo per modulo e per utente e tetto mensile.
4. Backup giornaliero del file DuckDB con rotazione.
5. Dockerfile e docker-compose con reverse proxy HTTPS.
6. Aggiorna docs/privacy.md con l'elenco completo dei trattamenti, preparato per la
   DPIA, e un README per lo staff su come usare ogni modulo.
7. Rivedi tutto il codice per dati personali salvati per errore e scrivi i test che
   lo impediscono.
```

Chiusura: un utente con ruolo comunicazione non vede le pagine di amministrazione; il backup si ripristina su una macchina pulita.
