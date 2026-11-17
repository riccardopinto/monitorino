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
