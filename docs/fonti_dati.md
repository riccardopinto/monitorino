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

## Fonti

Nessuna fonte caricata (Fase 0).

<!-- Fase 1: geodati del Comune di Torino (circoscrizioni, sezioni elettorali) -->
<!-- Fase 2: risultati elettorali per sezione, totali di controllo Eligendo -->
<!-- Fase 3: popolazione per circoscrizione, censimento ISTAT, redditi IRPEF per CAP -->
<!-- Fase 4: feed RSS delle testate locali, fonti social con API ufficiali -->
