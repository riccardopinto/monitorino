# Fonti dati

Registro di ogni fonte usata dalla piattaforma. Ogni script in `app/ingest/` aggiunge o aggiorna la sua sezione quando scarica dati nuovi. I file originali restano in `data/raw/<fonte>/<data>/` e non si modificano.

## Regole generali

### Normalizzazione dei codici

Codici di sezione e di circoscrizione sono **sempre stringhe**, mai numeri, e passano da `app/core/codici.py` prima di essere scritti nel database.

| Codice | Forma normalizzata | Esempi in ingresso | Funzione |
|---|---|---|---|
| Circoscrizione | `"1"` … `"8"`, senza zeri iniziali né prefissi | `03`, `3`, `Circoscrizione 3`, `Circ. III` → `"3"` | `normalizza_circoscrizione` |
| Sezione elettorale | numero intero positivo in stringa, senza zeri iniziali né spazi | `0123`, ` 123 `, `123.0` → `"123"` | `normalizza_sezione` |

I valori che non rientrano nella regola, per esempio una sezione con lettere, fanno fallire l'ingest. Si corregge la regola oppure si gestisce il caso in modo esplicito; il valore non va scartato in silenzio.

Le sezioni elettorali cambiano nel tempo: la corrispondenza sezione → circoscrizione si legge da `sezione_area` per l'anno dell'elezione.

### Dati di prova

I dati in `data/fixtures/` sono inventati per lo sviluppo. Ogni caricamento da lì scrive una riga in `caricamento` con `di_prova = true`, e finché esiste una riga così la dashboard mostra l'etichetta "DATI DI PROVA".

### Controlli minimi

Per ogni consultazione, la somma dei voti per circoscrizione e per comune deve coincidere con i totali ufficiali del Comune o di Eligendo. Il test relativo sta in `tests/`.

## Schema di registrazione

Copiare questo blocco per ogni nuova fonte.

```
### <Nome fonte>

| Campo | Valore |
|---|---|
| Ente / editore | |
| URL | |
| Data di download | AAAA-MM-GG |
| Licenza | |
| Formato | (CSV, shapefile, GeoJSON, XLSX…; codifica; separatore; sistema di riferimento) |
| Copertura | (anni, livello territoriale) |
| Script | `app/ingest/<fonte>.py` |
| Cartella raw | `data/raw/<fonte>/<data>/` |
| Tabelle scritte | |

Note sul formato: (colonne, anomalie, codici da normalizzare, differenze tra anni)
```

### Geometrie

Tutte le geometrie sono salvate in WGS84 (EPSG:4326). Le operazioni metriche (Voronoi, superfici) si fanno in WGS84 / UTM 32N (EPSG:32632). Il frontend riceve GeoJSON semplificato (tolleranza circa 5 m, coordinate a 6 decimali).

## Fonti

### Circoscrizioni (Comune di Torino, geoportale)

| Campo | Valore |
|---|---|
| Ente / editore | Città di Torino, geoportale |
| URL | http://geoportale.comune.torino.it/geodati/zip/circoscrizioni_geo.zip |
| Scheda | https://aperto.comune.torino.it/dataset/circoscrizioni |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Formato | shapefile zippato; EPSG:3003 (Monte Mario / Italy zone 1, Gauss-Boaga fuso Ovest); 8 feature (7 Polygon, 1 MultiPolygon) |
| Copertura | 8 circoscrizioni, assetto in vigore dal 2016 |
| Script | `app/ingest/circoscrizioni.py` |
| Cartella raw | `data/raw/comune_circoscrizioni/<data>/` |
| Tabelle scritte | `area` (tipo `circoscrizione`) |

Note sul formato: campi `NCIRCO` (numero) e `DENOM` (nome con quartieri separati da trattino; la 7 usa anche una virgola). La superficie totale risulta 130,0 km². Rispetto a `config/segmenti.yaml` l'unica differenza di contenuto è la circoscrizione 2: il geoportale scrive "Santa Rita - Mirafiori", senza distinguere Mirafiori Nord e Sud.

### Associazione indirizzi e seggi elettorali (Comune di Torino)

| Campo | Valore |
|---|---|
| Ente / editore | Città di Torino, Servizi elettorali |
| URL | https://risorse.comune.torino.it/opendata/elezioni/toseggio.csv |
| Scheda | https://aperto.comune.torino.it/dataset/associazione-indirizzi-e-seggi-elettorali |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Formato | CSV, UTF-8, separatore virgola, 62.570 righe |
| Copertura | 918 sezioni (da 1 a 919; manca la 912), rilascio 31-12-2017 |
| Script | `app/ingest/sezioni.py` |
| Cartella raw | `data/raw/comune_seggi/<data>/` |
| Tabelle scritte | `sezione_area` (anno 2017), `area` (tipo `sezione`, con i civici georeferenziati) |

Note sul formato:
- Colonne: `DESCRIZIONE_VIA, NUMERO_CIVICO, BIS/INTERNO/SCALA, CIRCOSCRIZIONE, SEZIONE, TIPO_FABBRICATO, DENOMINAZ_FABBRICATO, INDIRIZZO, CAP`.
- Le vie sono scritte con il cognome prima del nome (`VIA BARBAROUX GIUSEPPE`).
- Tre righe sono pseudo-indirizzi ("SENZA FISSA DIMORA", "VIA CENSIMENTO") con circoscrizione 0. Vengono escluse dalla geometria; la loro sezione (107) resta assegnata alla circoscrizione della maggioranza.
- Le sezioni 107 e 708 hanno un civico in una circoscrizione diversa dalle altre: vale la circoscrizione della maggioranza.
- Sei sezioni sono speciali, con un solo indirizzo istituzionale: 654 (Piccola Casa della Divina Provvidenza), 908, 909, 917, 918, 919 (ospedali). Restano in `sezione_area` ma senza confine.

### Numerazione civica 2019 (Comune di Torino)

| Campo | Valore |
|---|---|
| Ente / editore | Città di Torino |
| URL | https://risorse.comune.torino.it/opendata/geodata/civici_WGS84_EPSG4326_csv_201910.csv |
| Scheda | https://aperto.comune.torino.it/dataset/numerazione-civica |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Formato | CSV, UTF-8, separatore virgola, campi tra virgolette, decimali con la virgola; WGS84 (EPSG:4326); 118.118 civici |
| Copertura | ottobre 2019 |
| Script | `app/ingest/sezioni.py` |
| Cartella raw | `data/raw/comune_civici/<data>/` |
| Tabelle scritte | nessuna direttamente: serve a costruire i confini delle sezioni |

Note sul formato: le vie sono scritte con il nome prima del cognome (`VIA PIETRO PALMIERI`). Il civico è un campo unico con il suffisso (`59/A`, `63 scala B`, `138 bis/D`).

## Sezioni elettorali: confini approssimati

Il Comune non pubblica i confini delle sezioni elettorali (verificato il 2026-11-17 su aperto.comune.torino.it e sul geoportale). Li stimiamo dai due file sopra. Le aree risultanti hanno `area.approssimata = true` e la mappa lo dichiara.

**Metodo** (`app/ingest/sezioni.py`)
1. Abbinamento civico → sezione con i civici georeferenziati, sulla chiave (via, numero):
   - via: maiuscole, senza accenti né punteggiatura, parole in ordine alfabetico, così l'ordine nome/cognome non conta;
   - numero: parte numerica iniziale, senza lettere, bis o scala.
   - Una chiave associata a più sezioni prende quella della maggioranza delle righe.
2. Esito al 2026-11-17: 42.319 chiavi abbinate su 42.604 (99,3%). Lo script si ferma se l'esito scende sotto il 90%.
3. Dentro ogni circoscrizione: celle di Voronoi dei civici abbinati, ritagliate sul confine della circoscrizione e unite per sezione. Ogni sezione sta quindi nella sua circoscrizione, e le sezioni coprono la circoscrizione senza sovrapporsi (verificato: le superfici coincidono al m²).
4. Esito: 912 sezioni con confine su 918; 69 civici cadono fuori dalla circoscrizione dichiarata. Il dettaglio per sezione sta in `data/processed/sezioni_rapporto.csv`.

**Limiti**
- Parchi, fiume, collina e aree industriali senza civici finiscono nella sezione con il civico più vicino. Le sezioni periferiche risultano quindi più grandi del territorio realmente abitato.
- La corrispondenza civico → sezione è del 2017, i civici del 2019. Se il Comune ha ridisegnato le sezioni dopo il 2017, i confini non lo riflettono. In Fase 2 si confronta l'elenco delle sezioni con quello di ogni elezione.
- 184 sezioni risultano in più pezzi (MultiPolygon), soprattutto dove i civici di sezioni diverse si alternano lungo la stessa via.
- I confini servono a colorare la mappa, non a calcoli di precisione. I totali per circoscrizione si fanno sempre da `sezione_area`, mai da intersezioni geometriche.

### Risultati elettorali per sezione (Comune di Torino)

| Campo | Valore |
|---|---|
| Ente / editore | Città di Torino, Servizi elettorali |
| URL | https://elezioni.comune.torino.it (archivio: `/risultati/`; file in `/<anno>/<consultazione>/finali/`) |
| Data di download | 2026-11-17 |
| Licenza | non indicata sul sito; dati pubblici del Comune. Da verificare prima di ripubblicarli |
| Formato | CSV "Riepilogo per sezioni", separatore `;`, UTF-8 (alcuni file cp1252); consigli circoscrizionali in `circ1…8.zip` |
| Copertura | 919 sezioni per consultazione: comunali 2016 e 2021 (1° turno, ballottaggio, consigli circoscrizionali), Camera e Senato 2022, europee 2019 e 2024, regionali 2024 |
| Script | `app/ingest/elezioni/` (`consultazioni.py` elenca i file; `uv run python -m app.ingest.elezioni [chiave]`) |
| Cartella raw | `data/raw/elezioni_<consultazione>_<anno>/<data>/` |
| Tabelle scritte | `elezione`, `affluenza`, `risultato`, `sezione_area` (per anno), `lista_alias`, `totale_ufficiale` |

Note sul formato:
- Prima della riga d'intestazione ci sono alcune righe di preambolo: titolo, "LISTA: N - nome" nei file di preferenze, "SCRUTINATE n SEZIONI SU m". L'intestazione inizia con "Sezione": prima le colonne fisse, poi per ogni soggetto numero, nome ed eventuali etichette. Ogni riga di sezione ha le colonne fisse e poi i voti, separati da un campo vuoto. Spesso c'è una riga finale "TOTALE".
- Varianti gestite dal parser (`riepilogo.py`): colonna "Scrutinata" presente o no; valori con o senza virgolette (2024); due valori per candidato (voti e "voti solo sindaco/presidente/candidato": conta il primo); colonne fisse con nomi diversi tra anni.
- I nomi delle liste sono troncati a 30 caratteri.
- Le preferenze a zero non si salvano (assenza = 0). In `risultato.gruppo` c'è la lista del candidato, con il nome del file delle liste.
- I consigli circoscrizionali hanno solo liste e preferenze: il presidente lo elegge il consiglio, quindi non ci sono voti per il presidente.
- La corrispondenza sezione → circoscrizione si prende dai file dei risultati di ogni anno. Pochissime sezioni cambiano circoscrizione tra un anno e l'altro (da 1 a 3).
- Anomalie delle fonti, lasciate come sono:
  - nei file preferenze 2024 la riga TOTALE riporta gli iscritti raddoppiati (non usata);
  - nel file delle liste della Camera 2022 (collegio 1) la sezione 724 è marcata "N" (non scrutinata) ma ha i voti.
  - Le sezioni speciali (ospedali) hanno votanti ma 0 iscritti.

### Totali ufficiali di controllo (Ministero dell'Interno, Eligendo)

| Campo | Valore |
|---|---|
| Ente / editore | Ministero dell'Interno, Dipartimento per gli Affari interni e territoriali |
| URL | https://dait.interno.gov.it/documenti/opendata/<tipo>/<tipo>-AAAAMMGG.zip (indice: https://elezionistorico.interno.gov.it/eligendo/opendata.php) |
| Data di download | 2026-11-17 |
| Licenza | open data del Ministero, da verificare la licenza esatta |
| Formato | zip con CSV/TXT per comune di tutta Italia, separatore `;`; i ballottaggi comunali stanno nello stesso file del 1° turno (colonna TURNO) |
| Copertura | tutte le consultazioni caricate tranne i consigli circoscrizionali |
| Script | `app/ingest/elezioni/eligendo.py` |
| Cartella raw | `data/raw/eligendo/<data>/` |
| Tabelle scritte | `totale_ufficiale` (solo i totali di Torino) |

Controllo (`eligendo.differenze`): iscritti, votanti e bianche si confrontano con la somma delle sezioni. Liste e candidati si confrontano come insiemi di valori ordinati, perché i nomi sono scritti in modo diverso nei due file; se ogni voce coincide, i due elenchi di numeri sono identici. L'ingest si ferma se c'è una differenza non documentata in `config/scostamenti_noti.yaml`.

Esito al 2026-11-17: coincidenza esatta per tutte le consultazioni, con due eccezioni documentate e accettate dallo staff:
- comunali 2021: quattro liste differiscono di 1 voto, con somma zero (Noi Cittadini, Partito Animalista, Italexit, Futura per i Beni Comuni);
- Camera 2022: 1 votante in più nella somma per sezione (409.351 contro 409.350).

I file Eligendo contengono luogo e data di nascita dei candidati: non vengono salvati.

### Classificazione politica delle liste

`config/aree_politiche.yaml` assegna a ogni lista (e a ogni candidato sindaco o presidente) una **forza politica** normalizzata, confrontabile tra elezioni, e un'**area politica**: centrosinistra, centrodestra, M5S, civici e terzo polo, altro. Sono le stesse aree di `config/segmenti.yaml`, con "altro" al posto dell'astensione, che si ricava dall'affluenza.

La classificazione è una **proposta da verificare** dello staff. Regola usata:
- comunali e regionali: la lista prende l'area della coalizione del candidato collegato;
- coalizioni minori: "civici e terzo polo" se guidate da una civica, "altro" se guidate da un partito fuori dai due poli e dal M5S;
- politiche: coalizioni nazionali del 2022;
- europee: collocazione nazionale del partito.

Una lista nuova senza voce nel file ferma l'ingest.

### Popolazione per circoscrizione (Comune di Torino, Ufficio di statistica)

| Campo | Valore |
|---|---|
| Ente / editore | Città di Torino, Ufficio di statistica |
| URL | `https://www.comune.torino.it/media/<n>`: 9707, 9708, 9709 (età annuale totale, maschi, femmine), 9692 (genere, usato come controllo), 9735 e 9738 (stranieri per sesso e per età), 9722 (famiglie per tipologia), 9724 (stato civile). Schede su aperto.comune.torino.it |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Formato | CSV `;`, ASCII; una riga per voce, colonne `circ_1…circ_8` e `residenza_virtuale` (stranieri e genere: una riga per circoscrizione) |
| Copertura | residenti al 31/12/2025, per circoscrizione |
| Script | `app/ingest/demografia_comune.py` |
| Cartella raw | `data/raw/comune_demografia/<data>/` |
| Tabelle scritte | `demografia` (anno 2025) |

Note:
- `residenza_virtuale` raccoglie i residenti senza fissa dimora iscritti a un indirizzo fittizio (4.375 persone). Conta nel totale cittadino ma non appartiene a nessuna circoscrizione, quindi in `demografia` sta con `area_id = -1`.
- Controlli superati: età = maschi + femmine = file per genere in ogni circoscrizione; stranieri per età = stranieri per sesso. Totale: 863.249 residenti.
- Sotto la circoscrizione il Comune non pubblica dati recenti: la popolazione per zona statistica si ferma al 2006.

### Censimento permanente ISTAT 2021 per sezione di censimento

| Campo | Valore |
|---|---|
| Ente / editore | ISTAT |
| URL | variabili: https://esploradati.istat.it/databrowser/DWL/PERMPOP/SUBCOM/Dati_regionali_2021.zip (file `R01_indicatori_2021_sezioni.xlsx`, tracciato `TRACCIATO FILE REGIONALI.xlsx`); geometrie: https://www.istat.it/storage/cartografia/basi_territoriali/2021/R01_21.zip |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Formato | XLSX per regione; shapefile `SHP/R01_21_WGS84.shp` (malgrado il nome, in EPSG:32632) |
| Copertura | 4.292 sezioni di censimento abitate a Torino (6.916 in tutto), 848.748 residenti al 31/12/2021 |
| Script | `app/ingest/censimento_istat.py` |
| Cartella raw | `data/raw/istat_censimento_2021/<data>/`, `data/raw/istat_basi_territoriali/<data>/` |
| Tabelle scritte | `demografia` (anno 2021) per circoscrizioni e sezioni elettorali |

Variabili (prefisso `cens_`, dal tracciato ISTAT):
- popolazione: `cens_pop` (P1), per sesso (P2, P3), per classi quinquennali `cens_eta_00_04` … `cens_eta_75_piu` (P14-P29), anche per sesso (`cens_m_eta_*`, `cens_f_eta_*`);
- istruzione della popolazione di 9 anni e più (P83, P86-P90): `cens_istr_nessuno`, `_elementare`, `_media`, `_diploma`, `_terziario`;
- `cens_occupati_15_64` (P101), `cens_stranieri` (ST1), famiglie `cens_famiglie` e per numero di componenti (PF1, PF3-PF8), abitazioni ed edifici (A2, A8, E3).

Aggregazione:
- **per circoscrizione** con il codice ISTAT `COM_ASC1`: le aree sub-comunali di Torino sono le circoscrizioni;
- **per sezione elettorale** con il punto interno di ogni sezione di censimento che cade nei confini approssimati delle sezioni elettorali (Fase 1). I punti fuori dai confini vanno alla sezione più vicina.
- Esito: la circoscrizione ISTAT e quella della sezione elettorale coincidono per il 100% della popolazione. Le 4.044 sezioni di censimento con popolazione coprono 902 delle 912 sezioni elettorali con confine. Dettaglio in `data/processed/censimento_sezioni_elettorali.csv`.
- Nota tecnica: leggendo lo shapefile con un sottoinsieme di colonne, pyogrio restituisce POP21 a zero; lo script legge tutte le colonne.

### Tavole comunali IstatData (Torino)

| Campo | Valore |
|---|---|
| Ente / editore | ISTAT, IstatData (SDMX) |
| URL | `https://esploradati.istat.it/SDMXWS/rest/data/IT1,DF_DCSS_ISTR_LAV_PEN_2_TV_3,1.0/A.001272........` (popolazione di 15 anni e più per condizione professionale ed età) e `…/IT1,DF_DCSS_EMPLP_1_COM,1.0/A.001272.....` (occupati per posizione nella professione), formato CSV SDMX |
| Data di download | 2026-11-17 |
| Licenza | CC BY 4.0 |
| Copertura | Torino; condizione professionale 2018-2024 (si usa il 2024); posizione nella professione 2021 |
| Tabelle scritte | `demografia` con `area_id = 0` (comune intero): `istat_cond_<condizione>_eta_<classe>`, `istat_occupati_dipendenti`, `_indipendenti`, `_totale` |

Codici: condizione 1 occupato, 12 in cerca di occupazione, 24 percettore di pensione, 5 studente, 4 casalinga/o, 7 altra condizione, 99 totale; classi 15-24, 25-49, 50-64, 65+. Posizione: 9 dipendenti, 22 indipendenti (24,8% degli occupati nel 2021).

### Redditi IRPEF per CAP (MEF - Dipartimento delle Finanze)

| Campo | Valore |
|---|---|
| Ente / editore | MEF - Dipartimento delle Finanze (citare così) |
| URL | https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/Redditi_e_principali_variabili_IRPEF_su_base_subcomunale_CSV_2024.zip |
| Data di download | 2026-11-17 |
| Licenza | open data MEF, da verificare la licenza esatta |
| Formato | CSV `;`, una riga per CAP; alcune classi di reddito sono oscurate (vuote) per riservatezza: si usano solo i totali |
| Copertura | anno d'imposta 2024, 33 CAP di Torino, 641.857 contribuenti |
| Script | `app/ingest/redditi_mef.py` |
| Tabelle scritte | `demografia` (anno 2024): `mef_contribuenti`, `mef_reddito_complessivo_n`, `mef_reddito_complessivo_eur`, `mef_reddito_imponibile_eur`, `mef_imposta_netta_eur`, `mef_lavoro_dipendente_eur`, `mef_pensione_eur` |

**Ripartizione CAP → aree (stima)**. I confini dei CAP non sono pubblicati.
- I civici georeferenziati del Comune (2019, con CAP) si assegnano alle sezioni di censimento.
- La popolazione ISTAT 2021 di ogni sezione si divide tra i CAP in proporzione ai suoi civici. Una sezione senza civici prende il CAP del civico più vicino.
- Ogni variabile di un CAP si distribuisce sulle circoscrizioni e sulle sezioni elettorali in proporzione a quella popolazione.
- Il totale cittadino (`area_id = 0`) è la somma esatta dei CAP e la ripartizione lo conserva (test).
- I 33 CAP del file coincidono con quelli dei civici.

Limiti: si assume che contribuenti e redditi di un CAP siano distribuiti come i residenti, e il numero di civici approssima la popolazione dentro una sezione di censimento. I valori per area sono stime, segnalate come tali nell'interfaccia.

### Indicatori derivati

Si calcolano in `app/analysis/demografia.py` come rapporti tra somme, così il valore cittadino è coerente con quello delle aree:
- **indice di vecchiaia**: residenti 65+ ogni 100 residenti 0-14;
- **quota stranieri**;
- **quota con titolo terziario**: sui residenti di 9 anni e più, l'unica base disponibile per sezione;
- **tasso di occupazione 15-64**: censimento 2021;
- **reddito medio dichiarato**: reddito complessivo / numero di dichiaranti, MEF 2024;
- **componenti per famiglia**: censimento 2021.

Circoscrizioni e città usano i dati del Comune 2025 dove esistono. Le sezioni elettorali usano sempre il censimento 2021, e il loro confronto cittadino usa la stessa fonte e lo stesso anno. Per le sezioni con meno di 100 residenti gli indicatori non si mostrano.

### News locali e comunicati (feed RSS)

| Fonte | Feed | Stato al 2026-11-17 |
|---|---|---|
| La Stampa Torino | https://www.lastampa.it/torino/rss | attivo (100 elementi) |
| Corriere Torino | https://xml2.corriereobjects.it/rss/homepage_torino.xml | **spento**: il feed risponde ma è fermo al novembre 2022 |
| la Repubblica Torino | https://torino.repubblica.it/rss/rss2.0.xml | attivo (100) |
| TorinoToday | https://www.torinotoday.it/rss | attivo (25) |
| Torino Oggi | https://www.torinoggi.it/rss.xml | attivo (20) |
| Quotidiano Piemontese | https://www.quotidianopiemontese.it/feed/ | attivo (20) |
| Lo Spiffero | https://www.lospiffero.com/rss.xml | attivo (30) |
| Comunicati Città di Torino | https://www.torinoclick.it/feed/ (Torino Click, agenzia di stampa del Comune) | attivo (10) |
| Consigli di circoscrizione | nessun feed trovato | spento |

- Script: `app/temi/news.py` (comando `uv run python -m app.temi news`). L'XML originale va in `data/raw/news/<data>/`.
- Cosa si salva: titolo, link, data, testata e il sommario fornito dal feed, senza HTML e tagliato a 300 caratteri. Il testo integrale degli articoli non si scarica.
- Gli articoli con più di 30 giorni si scartano: un feed fermo si vede dagli esiti della raccolta.
- I feed comprendono notizie della provincia. La classificazione marca `pertinente = false` quelle che non riguardano la città, e l'aggregazione le esclude.
- Termini d'uso: i feed RSS sono pubblicati per la consultazione. Titoli e sommari si usano solo per l'analisi interna e si mostrano con il link all'articolo originale. Verificare con il consulente l'eventuale riuso esterno.

### Social (connettori spenti)

| Piattaforma | Accesso | Credenziali (.env) | Note |
|---|---|---|---|
| Reddit | Data API ufficiale, OAuth application-only | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (app "script" su reddit.com/prefs/apps) | senza credenziali risponde 403; verificare i termini della Data API per l'uso da parte di una campagna |
| YouTube | YouTube Data API v3 | `YOUTUBE_API_KEY` (Google Cloud) | id dei canali in `config/fonti.yaml`; 1 unità di quota per chiamata |
| Bluesky | API AT Protocol con sessione | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | la ricerca pubblica senza account risponde 403 dal 2025 |

Si attivano con `attiva: true` in `config/fonti.yaml` e le credenziali in `.env`; comando `uv run python -m app.temi social`.
- Alla raccolta restano solo testo e data: autore, ID e link non escono dal connettore.
- Dal testo si tolgono menzioni (`@nome`, `u/nome`), URL ed email.
- In `documento` i social hanno `url` NULL e `impronta` = hash del testo, mai l'ID.
- Il testo si cancella alla `scadenza` (30 giorni, comando `pulisci`). Restano tema, sentiment, area e la sintesi neutra della classificazione.

### Dizionario dei luoghi

`app/temi/luoghi.py` (comando `uv run python -m app.temi luoghi`) costruisce la tabella `luogo`, circa 4.900 voci.
- **Vie** dai civici 2019: una via entra solo se almeno l'80% dei suoi civici sta in una circoscrizione. Si usano il nome completo e la forma breve tipo + ultima parola.
- **Quartieri** dai nomi delle circoscrizioni. I nomi troppo comuni (Centro, Barca, Sassi, Aurora, Parella, Lucento) valgono solo con "quartiere", "borgo" o "zona" davanti.
- **Mercati, impianti sportivi, biblioteche, scuole** dal geoportale del Comune (`mercati_geo.zip`, `impianti_sportivi_geo.zip`, `biblioteche_geo.zip`, `scuole_geo.zip`, colonna `CIRCOSCRIZ`).
- Le forme che portano a più circoscrizioni si scartano.
- Assegnazione di un documento: si cercano i luoghi in titolo, sintesi e testo, preferendo la corrispondenza più lunga. Il documento va alla circoscrizione se è l'unica citata, oppure se ha almeno il doppio delle citazioni della seconda; altrimenti resta a livello cittadino.
- Al primo giro il 9% delle news ha ricevuto una circoscrizione dal dizionario. La classificazione può aggiungerne altre, solo dove il dizionario non ne ha trovata.

### Classificazione per tema

Le istruzioni sono comuni (`app/llm/prompt_temi.py`) e i campi richiesti sono:
- tema dalla tassonomia di `config/temi.yaml`, più "altro";
- `pertinente` (riguarda la città di Torino);
- sentiment da -2 a +2;
- circoscrizione, solo se chiara;
- sintesi neutra di massimo 25 parole.

La risposta è JSON con schema, validata con pydantic. I flussi sono due:
- **chat**: `uv run python -m app.temi esporta` scrive `data/processed/temi_prompt_<data>_<n>.md`, 150 documenti per file; `importa FILE` salva il JSON della risposta. Gli stessi due passi si fanno dal riquadro "Classificazione" del modulo Temi;
- **API**: `uv run python -m app.temi classifica` usa la Message Batches API con `MODELLO_CLASSIFICAZIONE`, 20 documenti per richiesta, istruzioni in cache, il 50% di sconto e il tetto di spesa. I batch in corso stanno in `data/processed/batch_temi.json` e si raccolgono all'esecuzione successiva.

Una classificazione già salvata non si sovrascrive. L'aggregazione settimanale (`aggrega`) usa solo i documenti classificati e pertinenti.

## Flussi elettorali stimati

`app/analysis/elezioni.py::flussi` stima la matrice di transizione tra le aree politiche di due elezioni, con il "non voto" come categoria aggiuntiva.

**Metodo**: regressione ecologica di Goodman con vincoli. Per ogni sezione si calcolano le quote sugli iscritti (aree politiche e non voto) nelle due elezioni. Si cerca la matrice B, con valori tra 0 e 1 e righe che sommano a 1, che minimizza lo scarto quadratico tra le quote di arrivo e quelle previste (quote di partenza × B), pesato per gli iscritti. Il calcolo usa `scipy.optimize` (SLSQP).

**Sezioni usate**: quelle presenti in entrambe le elezioni con iscritti > 0 e variazione degli iscritti sotto il 10%. Restano escluse le sezioni ospedaliere e quelle ridisegnate. Per una circoscrizione si usano le sue sezioni nell'anno dell'elezione di arrivo. Servono almeno 20 sezioni.

**Limiti, da dichiarare sempre**:
- È una stima su dati aggregati (inferenza ecologica): non descrive il comportamento di nessun elettore.
- L'ipotesi è che i comportamenti siano simili tra sezioni; dove non lo sono, la stima si distorce.
- Il non voto include bianche e nulle.
- Tra le due elezioni la popolazione degli iscritti cambia (decessi, nuovi elettori, trasferimenti).
- L'R² per colonna indica quanto la stima spiega la variabilità tra sezioni; valori bassi o negativi rendono inaffidabile quella colonna.
<!-- Fase 3: popolazione per circoscrizione, censimento ISTAT, redditi IRPEF per CAP -->
<!-- Fase 4: feed RSS delle testate locali, fonti social con API ufficiali -->
