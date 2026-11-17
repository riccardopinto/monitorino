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

<!-- Fase 2: risultati elettorali per sezione, totali di controllo Eligendo -->
<!-- Fase 3: popolazione per circoscrizione, censimento ISTAT, redditi IRPEF per CAP -->
<!-- Fase 4: feed RSS delle testate locali, fonti social con API ufficiali -->
