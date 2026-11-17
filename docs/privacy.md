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
| T2 | Demografia per area | aggregati statistici pubblici | — | da verificare | durata del progetto | attivo dalla Fase 3 |
| T3 | Raccolta news locali | titolo, URL, data, sommario del feed (max 300 caratteri); nessun testo integrale | persone citate negli articoli | da verificare | da definire | attivo dalla Fase 4 |
| T4 | Raccolta social pubblici | testo senza autore né identificativi, poi solo aggregati | autori dei contenuti pubblici | da verificare | testo ≤ 30 giorni, aggregati per la durata del progetto | pronto, spento (servono credenziali) |
| T5 | Simulazioni del laboratorio messaggi | proposte, persone sintetiche, risultati aggregati, sondaggi pubblicati per la calibrazione | nessuno (dati sintetici e aggregati) | da verificare | da definire | attivo dalla Fase 5 |
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

### Fase 2 — Storico elettorale

- Caricati i risultati per sezione elettorale di 11 consultazioni (2016-2024) dal sito del Comune, e i totali comunali dagli open data del Ministero dell'Interno. Il trattamento T1 è attivo.
- Sono dati aggregati: l'unità minima è la sezione, circa 750 iscritti. Nessun dato su singoli elettori.
- Si salvano i nomi dei candidati (sindaco, presidente, consiglieri, uninominali) e i voti di preferenza per sezione. Sono dati resi pubblici dalle liste elettorali e dagli uffici elettorali, ma riguardano persone fisiche, anche avversari politici: vanno usati solo per l'analisi dei risultati. La base giuridica è da verificare con il consulente.
- I file del Ministero contengono anche data e luogo di nascita dei candidati: si leggono solo i totali e quei dati non si salvano.
- Le sezioni speciali (ospedali, Cottolengo) hanno pochi votanti. A quel livello i voti di preferenza possono essere molto pochi: valutare con il consulente se nascondere in interfaccia le preferenze delle sezioni sotto una soglia.
- La classificazione delle liste per area politica (`config/aree_politiche.yaml`) è una scelta analitica dello staff, non un dato ufficiale.
- I flussi elettorali sono stime ecologiche e l'interfaccia lo dichiara accanto a ogni tabella, insieme all'avvertenza che i dati per area non descrivono i singoli.

### Fase 3 — Demografia

- Caricati dati statistici aggregati: popolazione per circoscrizione del Comune (2025), censimento ISTAT 2021 per sezione di censimento, redditi IRPEF per CAP del MEF (2024). Il trattamento T2 è attivo. Nessun dato su singole persone.
- **Piccoli numeri**: le sezioni di censimento possono contenere pochissimi residenti. Nel database restano solo le aggregazioni per circoscrizione e per sezione elettorale (centinaia di residenti), non le singole sezioni di censimento. In interfaccia gli indicatori delle sezioni elettorali con meno di 100 residenti non si mostrano. Da valutare con il consulente se la soglia è adeguata.
- I redditi per area sono stime da una ripartizione statistica e l'interfaccia lo dichiara.
- I pesi dei segmenti (`segmento_peso`) descrivono quote di gruppi aggregati per circoscrizione. Non contengono dati personali e non vanno usati per selezionare destinatari di annunci politici (Regolamento UE 2024/900). Metodo in `docs/metodo_simulazione.md`.
- Il grafico demografia/voto riporta sempre l'avvertenza sull'inferenza ecologica.

### Fase 4 — Temi da news e social

- **T3 attivo**: raccolta giornaliera di titoli, link e sommari dai feed RSS di 6 testate e dell'agenzia di stampa del Comune. Gli articoli possono citare persone (fatti di cronaca, politici). Non si salva il testo integrale, solo i sommari del feed (massimo 300 caratteri), usati per classificare. Durata di conservazione dei sommari da definire con il consulente; i dati aggregati restano per la durata del progetto.
- **T4 pronto ma spento**: i connettori Reddit, YouTube e Bluesky si attivano solo con le credenziali dello staff.
  - Minimizzazione alla fonte: si tengono solo testo e data, si tolgono menzioni, URL ed email. Non si salvano autore, ID o link (`documento.url` è NULL per i social).
  - Il testo si cancella alla scadenza di 30 giorni (`app/temi/aggrega.py::pulisci`, eseguito ogni giorno dal pianificatore o dal comando `pulisci`).
  - Test automatici verificano l'assenza di identificativi, sia sui connettori sia sul database reale.
  - Un testo anonimizzato può comunque contenere riferimenti a persone: per questo si cancella e in interfaccia non compare mai. Per i social l'interfaccia mostra solo conteggi aggregati.
- **Flusso di classificazione via chat**: il prompt esportato contiene titoli, sommari e, se i social sono attivi, i testi anonimizzati. Incollarlo in una chat significa inviare questi contenuti al fornitore della chat, come avviene con l'API. Usare un account di lavoro con le impostazioni di conservazione e addestramento verificate dal consulente, e non incollare prompt che contengano dati personali.
- **Fornitori**: si aggiungono le piattaforme social (Reddit, Google/YouTube, Bluesky), quando attivate, e il fornitore della chat usato per la classificazione. Da riportare nella sezione "Fornitori".

### Fase 5 — Laboratorio messaggi

- **T5 attivo**. Le simulazioni non trattano dati personali:
  - le persone del panel sono **sintetiche**, generate dal codice a partire dal seed: sesso, età, quartiere e due tratti presi da un elenco fisso. Non corrispondono a persone reali e non derivano da dati individuali;
  - il contesto del prompt contiene solo **aggregati** per circoscrizione: indicatori demografici, quote di voto 2021 per area politica, conteggi dei temi;
  - i pesi dei segmenti vengono dagli aggregati della Fase 3 (popolazione per età e condizione, voti per area). Nessun elettore è profilato e l'unità minima resta la circoscrizione.
- **Segmenti e pubblicità politica**: i segmenti servono a scrivere messaggi migliori, non a scegliere destinatari di annunci. L'interfaccia non esporta liste di persone o di segmenti per piattaforme pubblicitarie, e il limite è scritto in ogni risultato (Regolamento UE 2024/900).
- **Dicitura e limiti**: ogni risposta dell'API del laboratorio e ogni schermata dei risultati riporta "Simulazione IA, non è un sondaggio" e l'elenco dei limiti del metodo.
- **Frasi di reazione**: sono generate dal modello per persone inventate. L'interfaccia le presenta come tali e non vanno usate come citazioni di elettori reali. Il prompt della sintesi riceve solo numeri aggregati, non le frasi.
- **Contenuto conservato in `simulazione`**: proposta, parametri, panel, prompt di contesto, risposte grezze del modello, aggregati, sintesi e costo. La proposta può contenere riferimenti a persone o soggetti reali (es. un centro sociale), come qualsiasi testo di campagna: conservazione da definire con il consulente insieme alle bozze della Fase 6.
- **Calibrazione**: si registrano solo valori pubblicati di sondaggi (fonte, data, metrica, valore), non dati dei rispondenti.
- **Flusso via chat**: il prompt incollato nella chat contiene proposta, profilo pubblico del candidato, aggregati dell'area e panel sintetico; valgono le stesse cautele sul fornitore della chat indicate per la Fase 4.
- **Costi**: le simulazioni via API passano da `app/llm/client.py` (tetto mensile e conferma sopra `SOGLIA_CONFERMA_RUN_EUR`); quelle in chat hanno costo registrato zero.
