# Metodo del laboratorio messaggi

Prima stesura (Fase 3): descrive come si costruisce il panel di segmenti e come si pesano. La parte sulle chiamate al modello, l'aggregazione dei risultati e la calibrazione si scrive in Fase 5.

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
- L'astensione si misura sugli elettori, l'età sui residenti: residenti stranieri e non iscritti nelle liste elettorali entrano nella composizione per età ma non votano. Per ora i pesi non lo correggono; valutare in Fase 5 se usare gli elettori per fascia d'età, se il Comune li pubblica.
- Limiti propri dei modelli linguistici, da riportare in ogni report di simulazione: tendono a risposte moderate e prevedibili, sottostimano l'astensione e conoscono poco la cronaca locale recente.
