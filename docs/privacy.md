# Privacy e protezione dei dati

Documento di lavoro per preparare la valutazione d'impatto (DPIA, art. 35 GDPR). Si aggiorna a ogni fase. **Le basi giuridiche e le valutazioni vanno verificate da un consulente legale**: qui si descrive cosa fa il sistema, non un parere.

## Quadro normativo di riferimento

- GDPR, in particolare l'art. 9: le opinioni politiche sono dati di categoria particolare.
- Regolamento UE 2024/900 sulla trasparenza e il targeting della pubblicità politica, applicabile dal 10 ottobre 2025.
- Legge 28/2000 sulla par condicio.
- Termini d'uso delle piattaforme da cui si raccolgono contenuti.

## Principi di progetto

- Nessun profilo di singoli elettori. L'unità minima di analisi è la sezione elettorale o l'area statistica.
- I social si raccolgono solo da contenuti pubblici, tramite API ufficiali. Non si salvano autore, ID, foto o link al profilo. Il testo originale si cancella entro 30 giorni: il campo `documento.scadenza` è gestito da un job di pulizia, e `config/fonti.yaml` rifiuta valori oltre 30.
- I segmenti del laboratorio messaggi sono gruppi aggregati. Non diventano liste di destinatari per annunci.
- I contenuti generati restano in stato `bozza` finché un utente non li approva.
- Le simulazioni riportano sempre la dicitura "Simulazione IA, non è un sondaggio".

## Registro dei trattamenti

| # | Trattamento | Dati | Interessati | Base giuridica | Conservazione | Stato |
|---|---|---|---|---|---|---|
| T1 | Risultati elettorali per sezione | aggregati pubblici, nessun dato personale | — | da verificare | durata del progetto | non attivo (Fase 2) |
| T2 | Demografia per area | aggregati statistici pubblici | — | da verificare | durata del progetto | non attivo (Fase 3) |
| T3 | Raccolta news locali | titolo, URL, data, sintesi; nessun testo integrale | persone citate negli articoli | da verificare | da definire | non attivo (Fase 4) |
| T4 | Raccolta social pubblici | testo senza autore né identificativi, poi solo aggregati | autori dei contenuti pubblici | da verificare | testo ≤ 30 giorni, aggregati per la durata del progetto | non attivo (Fase 4) |
| T5 | Simulazioni del laboratorio messaggi | proposte, persone sintetiche, risultati aggregati | nessuno (dati sintetici) | da verificare | da definire | non attivo (Fase 5) |
| T6 | Bozze di contenuti | testi, fonti, autore della bozza | staff di campagna | da verificare | da definire | non attivo (Fase 6) |
| T7 | Utenti, accessi e audit | nome utente, ruolo, azioni, orari | staff di campagna | da verificare | da definire | non attivo (Fase 8) |
| T8 | Registro consumi API LLM | modulo, modello, token, costo, utente | staff di campagna | da verificare | da definire | struttura creata, campo `utente` vuoto fino alla Fase 8 |

## Fornitori e trasferimenti

| Fornitore | Uso | Dati inviati | Note |
|---|---|---|---|
| Anthropic (API Claude) | simulazioni, classificazione, generazione | proposte, contesti aggregati, testi da classificare | verificare termini, conservazione e trasferimenti extra UE |
| OpenStreetMap Foundation (tile.openstreetmap.org) | sfondo della mappa | il browser dello staff richiede le tile: indirizzo IP, user agent, zona della mappa visualizzata | dalla Fase 1; si disattiva con `MAPPA_SFONDO=nessuna`; rispettare la tile usage policy OSM (uso leggero, attribuzione visibile) |

## Misure di sicurezza

| Misura | Stato |
|---|---|
| Applicazione solo in locale o su server privato | previsto |
| Segreti solo in `.env`, escluso da git | attivo (Fase 0) |
| Database e dati grezzi esclusi da git | attivo (Fase 0) |
| Librerie frontend servite in locale, nessuna richiesta a CDN esterne | attivo (Fase 0) |
| Tetto di spesa mensile sulle chiamate LLM | attivo (Fase 0) |
| Login con password argon2, ruoli, cookie sicuri | previsto (Fase 8) |
| Audit di simulazioni, generazioni, approvazioni, export | previsto (Fase 8) |
| Backup giornaliero con rotazione | previsto (Fase 8) |
| HTTPS tramite reverse proxy | previsto (Fase 8) |
| Test che verificano l'assenza di dati identificativi | previsto (Fase 4 e 8) |

## Registro per fase

### Fase 0 — Impianto

- Nessun dato personale trattato e nessun dato scaricato.
- Create le tabelle `uso_llm` (con campo `utente`, valorizzato dalla Fase 8), `audit` e `documento`. Quest'ultima ha il campo `testo` destinato alla cancellazione alla `scadenza`.
- Le librerie frontend sono servite dal server dell'applicazione, così i browser dello staff non contattano CDN di terzi.

### Fase 1 — Mappa e geodati

- Caricati i confini delle circoscrizioni, la corrispondenza civico → sezione elettorale (2017) e i numeri civici georeferenziati (2019). Sono dati pubblici del Comune, sotto licenza CC BY 4.0.
- Non c'è nessun dato personale: i civici sono indirizzi di edifici, non riferiti a persone. Nel database restano solo i poligoni per sezione e la corrispondenza sezione → circoscrizione; l'elenco dei civici resta solo nei file originali in `data/raw/`.
- I confini delle sezioni sono stime e lo dichiarano (`area.approssimata`, avviso in mappa).
- Nuova richiesta esterna: le tile di sfondo OpenStreetMap (vedi "Fornitori"). Si può spegnere con `MAPPA_SFONDO=nessuna`.
