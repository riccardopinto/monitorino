# Metodo del laboratorio messaggi

Le sezioni "Segmenti" e "Pesi per circoscrizione" descrivono come si costruisce e si pesa il panel (Fase 3). "Simulazione" descrive run, chiamate al modello, aggregazione, sintesi e calibrazione (Fase 5).

Ogni risultato del laboratorio riporta la dicitura **"Simulazione IA, non è un sondaggio"**.

## Segmenti

I segmenti nascono da `config/segmenti.yaml` come incroci di tre dimensioni:
- **fascia d'età**: 18-29, 30-44, 45-64, 65+;
- **condizione**: studente, lavoratore dipendente, lavoratore autonomo, pensionato, in cerca di lavoro, casalingo/a;
- **area di voto**: centrosinistra, centrodestra, M5S, civici e terzo polo, astensione abituale.

Sono 4 × 6 × 5 = 120 segmenti. Ogni segmento ha una definizione stabile nella tabella `segmento`. I `segmenti_default` del file sono il sottoinsieme usato normalmente per contenere i costi.

I segmenti descrivono **gruppi aggregati** e servono a scrivere messaggi migliori. Non sono liste di persone e non devono diventare destinatari di annunci (Regolamento UE 2024/900).

## Pesi per circoscrizione

Per ogni circoscrizione e per ognuna delle due varianti (vedi sotto) si calcola il peso di ogni segmento, cioè la quota stimata di residenti maggiorenni che gli appartengono. I pesi di una circoscrizione sommano a 1. Stanno in `segmento_peso` (anno 2025) e si calcolano con:

```
uv run python -m app.analysis.demografia --pesi
```

Il peso di un segmento è il prodotto di tre quote:

**peso(fascia, condizione, area di voto) = P(fascia) × P(condizione | fascia) × P(area di voto)**

1. **P(fascia)**: residenti della circoscrizione per età singola al 31/12/2025 (Comune di Torino), raggruppati nelle quattro fasce, solo maggiorenni.

2. **P(condizione | fascia)**:
   - si parte dalla tavola ISTAT di Torino del 2024 (popolazione di 15 anni e più per condizione professionale e classe d'età 15-24, 25-49, 50-64, 65+);
   - ogni età singola eredita le quote della sua classe ISTAT, e la quota della fascia è la media pesata sui residenti di ciascuna età. Per esempio, la fascia 18-29 combina le quote della classe 15-24 (età 18-24) e della 25-49 (età 25-29);
   - la voce ISTAT "altra condizione" (circa il 7% dei 15+) non ha un segmento: si ripartisce in proporzione sulle altre condizioni;
   - "occupato" si divide in dipendente e autonomo con la quota cittadina ISTAT 2021: 24,8% di indipendenti. Per circoscrizione questo dato non esiste;
   - **adattamento alla circoscrizione**: nelle fasce in età da lavoro (18-29, 30-44, 45-64) la quota di occupati si moltiplica per il rapporto tra il tasso di occupazione 15-64 della circoscrizione e quello cittadino (censimento 2021), e le altre condizioni si riscalano perché la riga sommi ancora a 1. È un raking su un solo margine, perché per sezione di censimento ISTAT pubblica solo gli occupati e non studenti, pensionati o disoccupati.

3. **P(area di voto)**: quote sugli **elettori** della circoscrizione.
   - variante **`comunali`**: comunali 2021, primo turno, voti ai candidati sindaco classificati per area (comprendono chi ha votato solo il sindaco);
   - variante **`nazionali`**: media semplice delle quote di europee 2024 e Camera 2022 (voti di lista);
   - l'area "altro" (liste fuori dalle aree dei segmenti) si ripartisce in proporzione sulle quattro aree politiche;
   - **astensione abituale** = 1 − somma delle quote: comprende non votanti, schede bianche e nulle;
   - le aree politiche vengono da `config/aree_politiche.yaml` (classificazione dello staff).

La variante attiva è in `config/segmenti.yaml` (`pesi_voto.attiva`); il laboratorio può usare l'una o l'altra.

Per una simulazione su tutta la città, i pesi delle circoscrizioni si combinano in proporzione ai residenti maggiorenni.

## Ipotesi e limiti da dichiarare

- **Indipendenza tra voto ed età/condizione** dentro la circoscrizione: per stimare la composizione congiunta non esistono dati. In realtà voto, età e condizione sono correlati: per esempio, i pensionati non votano come gli studenti della stessa circoscrizione. È un limite di inferenza ecologica; i pesi dicono quanto pesa un gruppo, non come vota.
- La condizione per età è cittadina (ISTAT), adattata alla circoscrizione solo sul tasso di occupazione.
- Anni diversi: popolazione 2025, condizione professionale 2024, occupazione per area 2021, voto 2021-2024.
- L'astensione si misura sugli elettori, l'età sui residenti: residenti stranieri e non iscritti nelle liste elettorali entrano nella composizione per età ma non votano. Per ora i pesi non lo correggono: da rivedere se il Comune pubblica gli elettori per fascia d'età.
- Limiti propri dei modelli linguistici, da riportare in ogni report di simulazione: tendono a risposte moderate e prevedibili, sottostimano l'astensione e conoscono poco la cronaca locale recente.

## Simulazione (Fase 5)

### 1. Run

Un run riceve:
- la **proposta** (testo) e una **variante B** facoltativa;
- il **candidato** che la presenta (da `config/candidati.yaml`);
- le **aree**: una o più circoscrizioni, oppure tutta la città (le 8 circoscrizioni);
- i **segmenti**: i `segmenti_default`, una selezione libera tra i 120, oppure l'**elettorato potenziale** del candidato (`elettorato_potenziale` in `candidati.yaml`, che filtra le aree di voto);
- il numero di **persone sintetiche** per segmento (default 10);
- la **variante dei pesi di voto** (`comunali` o `nazionali`);
- un **seed** (numero intero).

### 2. Panel deterministico

Dal seed, con `random.Random(seed)`, il codice genera il profilo di ogni persona sintetica:
- sesso, con quote dalla popolazione della circoscrizione;
- età esatta dentro la fascia del segmento, secondo la distribuzione per età della circoscrizione;
- quartiere della circoscrizione;
- un tratto preso da un elenco fisso (es. "ha figli piccoli", "usa i mezzi pubblici", "ha un'attività in zona").

Stesso seed vuol dire stesso panel e stesso prompt. **Le risposte del modello possono comunque variare tra un run e l'altro**: con la versione attuale dell'API Anthropic il parametro `temperature` non si può impostare, quindi la ripetibilità riguarda il panel e i prompt, non le risposte. Il valore salvato per la temperatura è "non usata".

Il **confronto A/B** usa lo stesso panel per A e per B, nella stessa chiamata (disegno appaiato). La differenza tra le due versioni non dipende dalla composizione del panel, e ogni persona valuta entrambe.

### 3. Contesto per area

Per ogni circoscrizione il prompt contiene un blocco di contesto, uguale per tutti i segmenti dell'area, che via API sta in cache:
- dati demografici della circoscrizione a confronto con la città (indicatori della Fase 3);
- risultati delle comunali 2021 per area politica e affluenza;
- i temi più discussi delle ultime 4 settimane (`tema_aggregato`), con il sentiment medio;
- il profilo del candidato: nome, lista, ruolo, tono di voce e posizioni approvate, solo se compilati in `candidati.yaml`.

### 4. Chiamata per segmento e area

Il modello (`MODELLO_SIMULAZIONE`) interpreta le persone del panel di quel segmento e di quell'area. Per ogni persona restituisce, in JSON validato con pydantic:
- **gradimento** da 1 a 5;
- **effetto sul voto**: allontana, nessuno o avvicina;
- **timori**, fino a 3;
- **parole ricordate**, fino a 3;
- una **frase di reazione**.

Con una variante B, ogni persona riceve una valutazione per A e una per B. Una risposta con valori fuori scala o persone mancanti viene rifiutata.

### 5. Aggregazione

- **Per segmento e area**: gradimento medio e deviazione standard, percentuali allontana/nessuno/avvicina, **saldo netto** = % avvicina − % allontana.
- **Per area**: media pesata dei segmenti con i pesi della variante scelta (`segmento_peso`), rinormalizzati sui segmenti inclusi nel run.
- **Città**: media delle aree pesata sui residenti maggiorenni.
- **Obiezioni**: i timori si normalizzano (minuscole, senza parole vuote) e si raggruppano quando hanno parole significative in comune. Si mostra il numero di persone per gruppo, pesato sui segmenti.
- **Frasi rappresentative**: per ogni segmento, la reazione più vicina al gradimento medio e le due estreme.

### 6. Sintesi

Il modello di sintesi (`MODELLO_SINTESI`) riceve solo gli aggregati, non le risposte individuali, e scrive:
- chi apprezza;
- chi si oppone e perché;
- i rischi;
- i suggerimenti di riformulazione.

Ogni affermazione deve rimandare ai numeri del run.

### 7. Esecuzione e costi

- **Via API**:
  - una chiamata per segmento e area, in parallelo con al massimo 4 chiamate contemporanee;
  - sopra le 40 chiamate si usa la Message Batches API, con il 50% di sconto e risultati entro 24 ore;
  - prima del lancio si mostra la stima del costo, e sopra `SOGLIA_CONFERMA_RUN_EUR` serve una conferma esplicita. Vale il tetto mensile.
- **Via chat**, senza chiave:
  - un prompt per area con al massimo 5 segmenti (circa 50 persone, per restare nei limiti di una risposta);
  - il JSON di ogni blocco si reimporta, e il run si completa quando arrivano tutti i blocchi;
  - la sintesi si esporta e si reimporta allo stesso modo;
  - costo registrato: zero.

### 8. Salvataggio

Tabella `simulazione`:
- proposta, aree, segmenti, modello, seed, variante dei pesi, origine (api o chat), stato e costo;
- nei parametri: candidato, persone per segmento, versione del metodo, testo esatto di ogni prompt, temperatura "non usata";
- nei risultati: risposte grezze, aggregati e sintesi.

Le varianti A e B stanno nello stesso run.

### 9. Calibrazione

Quando esce un sondaggio reale sullo stesso tema, lo si collega a una simulazione:
- metrica, per esempio "% favorevoli" = gradimento 4-5, oppure "% che si avvicina";
- valore simulato, valore reale, fonte del sondaggio.

Lo scarto va in `calibrazione`. L'interfaccia mostra un **indice di affidabilità**: numero di calibrazioni e scarto medio assoluto in punti percentuali. Senza calibrazioni mostra "affidabilità non stimata".

### 10. Limiti da dichiarare in ogni risultato

- Gli LLM tendono a risposte moderate e prevedibili, sottostimano l'astensione e conoscono poco la cronaca locale recente.
- Le persone sintetiche rappresentano segmenti, non individui reali. I pesi assumono che voto, età e condizione siano indipendenti dentro un'area (inferenza ecologica).
- Il risultato aiuta a scegliere parole e argomenti. Non stima il consenso e non va citato come sondaggio.
- I segmenti non sono liste di destinatari per annunci (Regolamento UE 2024/900).
