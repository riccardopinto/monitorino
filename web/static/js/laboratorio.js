// Modulo "Laboratorio messaggi": crea simulazioni, flusso chat (prompt da copiare e JSON da
// caricare) o API, risultati pesati, confronto A/B, sintesi, archivio e calibrazione.
// Ogni risultato porta la dicitura "Simulazione IA, non è un sondaggio".
(() => {
  const NEGATIVO = "#d6604d"; // rosso e blu della scala divergente (scale.js)
  const POSITIVO = "#4393c3";
  const NEUTRO = "#bdbdbd";
  const BASE = "/api/laboratorio";
  const grafici = {};

  async function json(url, opzioni) {
    const r = await fetch(url, opzioni);
    if (!r.ok) {
      let dettaglio = `HTTP ${r.status}`;
      try {
        dettaglio = (await r.json()).detail || dettaglio;
      } catch (_) {}
      const e = new Error(typeof dettaglio === "string" ? dettaglio : dettaglio.messaggio || JSON.stringify(dettaglio));
      e.dettaglio = dettaglio;
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  const testo = (url, corpo) =>
    json(url, { method: "POST", headers: { "Content-Type": "text/plain" }, body: corpo });

  const segno = (v, cifre = 1) =>
    v === null || v === undefined ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(cifre).replace(".", ",");
  const num = (v, cifre = 1) => (v === null || v === undefined ? "–" : v.toFixed(cifre).replace(".", ","));
  const nomeSegmento = (s) => `${s.fascia_eta} · ${s.condizione} · ${s.area_di_voto}`;

  document.addEventListener("alpine:init", () => {
    Alpine.store("lab", {
      opzioni: null,
      archivio: [],
      affidabilita: null,
      run: null,
      errore: null,
      occupato: false,
      conferma: null, // { costo_eur } quando serve la conferma sopra soglia
      vista: "a",
      areaSegmenti: "",
      bloccoIncolla: 1,
      testoIncolla: "",
      esitoImport: null,
      testoSintesi: "",
      copiato: null,
      cal: { fonte: "", metrica: "favorevoli_pct", valore: null, data: "", variante: "a", area: "" },
      esitoCal: null,
      legenda: [],
      form: {
        proposta: "",
        conB: false,
        proposta_b: "",
        candidato: "sindaco",
        modoAree: "scelte", // scelte | citta | mappa
        aree: ["3"],
        modoSegmenti: "predefiniti", // predefiniti | elettorato | liberi
        fasce: [],
        condizioni: [],
        areeVoto: [],
        persone: 10,
        variante: "comunali",
        seed: 1,
        origine: "chat",
      },
      segno,
      num,
      nomeSegmento,

      // --- form ------------------------------------------------------------
      candidato() {
        return this.opzioni?.candidati.find((c) => c.chiave === this.form.candidato) || null;
      },
      areeScelte() {
        if (this.form.modoAree === "citta") return this.opzioni?.circoscrizioni.map((c) => c.codice) || [];
        if (this.form.modoAree === "mappa") {
          const a = Alpine.store("selezione").area;
          if (!a) return [];
          return [a.tipo === "sezione" ? a.circoscrizione : a.codice];
        }
        return [...this.form.aree].sort();
      },
      segmentiScelti() {
        if (!this.opzioni) return [];
        if (this.form.modoSegmenti === "predefiniti") return this.opzioni.segmenti_predefiniti;
        if (this.form.modoSegmenti === "elettorato") return this.candidato()?.segmenti_elettorato || [];
        const out = [];
        for (const fascia_eta of this.form.fasce)
          for (const condizione of this.form.condizioni)
            for (const area_di_voto of this.form.areeVoto) out.push({ fascia_eta, condizione, area_di_voto });
        return out;
      },
      riepilogoForm() {
        const a = this.areeScelte().length;
        const s = this.segmentiScelti().length;
        const blocchi = a * Math.ceil(s / (this.opzioni?.segmenti_per_blocco || 5));
        const persone = a * s * this.form.persone;
        return this.form.origine === "chat"
          ? `${s} segmenti × ${a} circoscrizioni = ${persone} persone sintetiche, ${blocchi} prompt da incollare in chat`
          : `${s} segmenti × ${a} circoscrizioni = ${a * s} chiamate API, ${persone} persone sintetiche`;
      },
      puoCreare() {
        return (
          !this.occupato &&
          this.form.proposta.trim().length >= 3 &&
          this.areeScelte().length > 0 &&
          this.segmentiScelti().length > 0 &&
          this.segmentiScelti().length <= 120 &&
          (!this.form.conB || this.form.proposta_b.trim().length >= 3)
        );
      },
      nuovoSeed() {
        this.form.seed = Math.floor(Math.random() * 100000);
      },

      // --- caricamento -----------------------------------------------------
      async avvia() {
        try {
          if (!this.opzioni) {
            this.opzioni = await json(`${BASE}/opzioni`);
            this.form.persone = this.opzioni.persone_per_segmento;
            this.form.variante = this.opzioni.variante_attiva;
          }
          await this.aggiornaArchivio();
          this.errore = null;
        } catch (e) {
          this.errore = e.message;
        }
        if (this.run) {
          await this.ridisegna();
        } else {
          window.MappaTorino?.pulisci();
        }
      },
      async aggiornaArchivio() {
        const [a, f] = await Promise.all([json(`${BASE}/simulazioni`), json(`${BASE}/affidabilita`)]);
        this.archivio = a.simulazioni;
        this.affidabilita = f;
      },

      async crea() {
        if (!this.puoCreare()) return;
        this.occupato = true;
        this.errore = null;
        this.conferma = null;
        const f = this.form;
        try {
          const run = await json(`${BASE}/simulazioni`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              proposta: f.proposta,
              proposta_b: f.conB ? f.proposta_b : null,
              candidato: f.candidato,
              aree: this.areeScelte(),
              segmenti: this.segmentiScelti(),
              persone: f.persone,
              variante: f.variante,
              seed: f.seed,
              origine: f.origine,
            }),
          });
          await this.mostra(run);
          await this.aggiornaArchivio();
          if (run.origine === "api") await this.esegui(false);
        } catch (e) {
          this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },

      async apri(id) {
        try {
          await this.mostra(await json(`${BASE}/simulazioni/${id}`));
          this.errore = null;
        } catch (e) {
          this.errore = e.message;
        }
      },

      async mostra(run) {
        this.run = run;
        this.vista = "a";
        this.esitoImport = null;
        this.esitoCal = null;
        this.testoSintesi = "";
        this.copiato = null;
        const prossimo = run.blocchi.find((b) => !b.completato);
        this.bloccoIncolla = prossimo ? prossimo.n : 1;
        const sel = Alpine.store("selezione").area;
        const circ = sel ? (sel.tipo === "sezione" ? sel.circoscrizione : sel.codice) : null;
        this.areaSegmenti = run.aree.includes(circ) ? circ : run.aree[0];
        this.cal.area = "";
        await this.ridisegna();
      },

      // --- flusso API ------------------------------------------------------
      async esegui(conferma) {
        this.occupato = true;
        this.errore = null;
        try {
          const esito = await json(`${BASE}/simulazioni/${this.run.id}/avvia?conferma=${conferma}`, { method: "POST" });
          this.conferma = null;
          await this.mostra(esito.simulazione);
          await this.aggiornaArchivio();
        } catch (e) {
          if (e.status === 409 && e.dettaglio?.conferma_richiesta) this.conferma = e.dettaglio;
          else this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },
      async aggiornaBatch() {
        this.occupato = true;
        try {
          const esito = await json(`${BASE}/simulazioni/${this.run.id}/batch`, { method: "POST" });
          await this.mostra(esito.simulazione);
          if (esito.stato === "in_attesa") this.errore = "Il batch è ancora in elaborazione: riprova più tardi.";
        } catch (e) {
          this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },

      // --- flusso chat -----------------------------------------------------
      urlPrompt(n) {
        return `${BASE}/simulazioni/${this.run.id}/prompt/${n}`;
      },
      async copiaPrompt(n) {
        try {
          const r = await fetch(this.urlPrompt(n));
          await navigator.clipboard.writeText(await r.text());
          this.copiato = n;
          this.bloccoIncolla = n;
        } catch (e) {
          this.errore = "Copia non riuscita: usa il download. " + e.message;
        }
      },
      async importa(n, corpo) {
        this.occupato = true;
        this.esitoImport = null;
        this.errore = null;
        try {
          const esito = await testo(`${BASE}/simulazioni/${this.run.id}/risposte/${n}`, corpo);
          this.esitoImport = `Blocco ${n} importato (${esito.completati.length} di ${esito.totale_blocchi}).`;
          this.testoIncolla = "";
          await this.mostra(esito.simulazione);
          await this.aggiornaArchivio();
        } catch (e) {
          this.errore = `Blocco ${n}: ${e.message}`;
        } finally {
          this.occupato = false;
        }
      },
      async caricaFile(n, evento) {
        const file = evento.target.files?.[0];
        if (!file) return;
        await this.importa(n, await file.text());
        evento.target.value = "";
      },

      // --- sintesi ---------------------------------------------------------
      async sintesiApi() {
        this.occupato = true;
        try {
          this.run = await json(`${BASE}/simulazioni/${this.run.id}/sintesi-api`, { method: "POST" });
        } catch (e) {
          this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },
      async copiaPromptSintesi() {
        try {
          const r = await fetch(`${BASE}/simulazioni/${this.run.id}/prompt-sintesi`);
          await navigator.clipboard.writeText(await r.text());
          this.copiato = "sintesi";
        } catch (e) {
          this.errore = "Copia non riuscita: usa il download. " + e.message;
        }
      },
      async salvaSintesi() {
        if (!this.testoSintesi.trim()) return;
        try {
          this.run = await testo(`${BASE}/simulazioni/${this.run.id}/sintesi`, this.testoSintesi);
          this.testoSintesi = "";
        } catch (e) {
          this.errore = e.message;
        }
      },

      // --- calibrazione ----------------------------------------------------
      async calibra() {
        this.esitoCal = null;
        try {
          const c = this.cal;
          const esito = await json(`${BASE}/calibrazioni`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              simulazione_id: this.run.id,
              fonte_sondaggio: c.fonte,
              metrica: c.metrica,
              valore_reale: c.valore,
              data_sondaggio: c.data || null,
              variante: c.variante,
              area: c.area || null,
            }),
          });
          this.esitoCal = `Registrato: simulato ${num(esito.valore_simulato)}, reale ${num(esito.valore_reale)}, scarto ${segno(esito.scarto)} punti.`;
          this.affidabilita = { ...this.affidabilita, ...esito.affidabilita };
          this.cal.fonte = "";
          this.cal.valore = null;
        } catch (e) {
          this.esitoCal = "Errore: " + e.message;
        }
      },

      // --- risultati -------------------------------------------------------
      aggregati() {
        return this.run?.aggregati?.[this.vista] || null;
      },
      segmentiArea() {
        return (this.aggregati()?.segmenti || []).filter((s) => s.area === this.areaSegmenti);
      },
      frasiArea() {
        return (this.aggregati()?.frasi || []).filter((f) => f.area === this.areaSegmenti);
      },
      confronto() {
        return this.run?.aggregati?.ab || null;
      },
      nomeArea(codice) {
        return this.opzioni?.circoscrizioni.find((c) => c.codice === codice)?.nome || "";
      },
      statoTesto() {
        const r = this.run;
        if (!r) return "";
        if (r.stato === "completata") return "completata";
        if (r.stato === "errore") return "con errori";
        if (r.batch) return "batch in elaborazione";
        if (r.origine === "chat")
          return `in attesa: ${r.blocchi.filter((b) => b.completato).length} di ${r.blocchi.length} blocchi importati`;
        return "in attesa di avvio";
      },

      async ridisegna() {
        await new Promise((ok) => Alpine.nextTick(ok));
        this.aggiornaMappa();
        this.disegnaBarre("grafico-lab-voto", this.aggregati()?.aree_di_voto || [], (r) => r.area_di_voto);
        this.disegnaBarre("grafico-lab-segmenti", this.segmentiArea(), (r) => nomeSegmento(r));
      },

      async aggiornaMappa() {
        if (Alpine.store("selezione").modulo !== "laboratorio") return;
        const ag = this.aggregati();
        if (!ag) {
          window.MappaTorino.pulisci();
          this.legenda = [];
          return;
        }
        const valori = Object.fromEntries(ag.aree.map((a) => [a.area, a.saldo]));
        const scala = Scala.classi(Object.values(valori), true);
        const formato = (v) => `saldo ${segno(v)} punti`;
        this.legenda = Scala.legenda(scala, (v) => segno(v));
        await window.MappaTorino.colora("circoscrizione", valori, (v) => Scala.coloreDi(scala, v), formato);
      },

      disegnaBarre(id, righe, etichetta) {
        if (grafici[id]) {
          grafici[id].destroy();
          delete grafici[id];
        }
        const tela = document.getElementById(id);
        if (!tela || !righe.length) return;
        tela.parentElement.style.height = `${Math.max(90, righe.length * 26 + 40)}px`;
        grafici[id] = new Chart(tela, {
          type: "bar",
          data: {
            labels: righe.map(etichetta),
            datasets: [
              {
                label: "Saldo netto (punti)",
                data: righe.map((r) => r.saldo),
                backgroundColor: righe.map((r) => (r.saldo > 0 ? POSITIVO : r.saldo < 0 ? NEGATIVO : NEUTRO)),
                borderRadius: 4,
                borderSkipped: false,
                barThickness: 14,
              },
            ],
          },
          options: {
            indexAxis: "y",
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                min: -100,
                max: 100,
                grid: { color: (c) => (c.tick.value === 0 ? "#8a8f98" : "#ecebe8") },
                ticks: { color: "#5d6675", stepSize: 50, callback: (v) => segno(v, 0) },
              },
              y: { grid: { display: false }, ticks: { color: "#1d2330", font: { size: 10 } } },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: (c) => {
                    const r = righe[c.dataIndex];
                    return [
                      `Saldo ${segno(r.saldo)} punti`,
                      `Avvicina ${num(r.avvicina_pct)}% · allontana ${num(r.allontana_pct)}%`,
                      `Gradimento ${num(r.gradimento_medio, 2)} (dev. ${num(r.gradimento_dev, 2)})`,
                      `Persone sintetiche: ${r.n}`,
                    ];
                  },
                },
              },
            },
          },
        });
      },
    });

    Alpine.effect(() => {
      const modulo = Alpine.store("selezione").modulo;
      const s = Alpine.store("lab");
      queueMicrotask(() => {
        if (modulo === "laboratorio") s.avvia();
      });
    });

    // Clic su una circoscrizione del run: mostra i suoi segmenti.
    Alpine.effect(() => {
      const area = Alpine.store("selezione").area;
      const s = Alpine.store("lab");
      queueMicrotask(() => {
        if (Alpine.store("selezione").modulo !== "laboratorio" || !s.run || !area) return;
        const circ = area.tipo === "sezione" ? area.circoscrizione : area.codice;
        if (s.run.aree.includes(circ) && circ !== s.areaSegmenti) {
          s.areaSegmenti = circ;
          s.ridisegna();
        }
      });
    });
  });
})();
