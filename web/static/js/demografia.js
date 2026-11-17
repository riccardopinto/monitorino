// Modulo "Demografia": coropletica degli indicatori, scheda dell'area con piramide d'età,
// dispersione indicatore/voto con la nota sull'inferenza ecologica.
(() => {
  const COLORE_AREA = "#2a78d6"; // slot 1
  const COLORE_CITTA = "#eb6834"; // slot 2
  const fmt = (v, cifre = 1) =>
    v === null || v === undefined ? "–" : new Intl.NumberFormat("it-IT", { maximumFractionDigits: cifre }).format(v);

  let graficoPiramide = null;
  let graficoDispersione = null;

  async function json(url) {
    const r = await fetch(url);
    if (!r.ok) {
      let dettaglio = `HTTP ${r.status}`;
      try {
        dettaglio = (await r.json()).detail || dettaglio;
      } catch (_) {}
      throw new Error(dettaglio);
    }
    return r.json();
  }

  function formatoValore(v, unita) {
    if (unita === "%") return `${fmt(v)}%`;
    if (unita === "euro") return `${fmt(v, 0)} €`;
    if (unita === "persone") return fmt(v, v > 100 ? 0 : 2);
    return fmt(v);
  }

  document.addEventListener("alpine:init", () => {
    Alpine.store("demografia", {
      indicatori: [],
      indicatore: "reddito_medio",
      livello: "circoscrizione",
      legenda: [],
      mappa: null, // risposta di /api/demografia/mappa
      scheda: null,
      erroreScheda: null,
      // dispersione indicatore / voto
      elezioni: [],
      elezione: null,
      soggetto: "centrosinistra",
      dispersione: null,
      erroreDispersione: null,
      errore: null,

      get corrente() {
        return this.indicatori.find((i) => i.chiave === this.indicatore) || null;
      },
      get soggettiAree() {
        return this.elezioni.find((e) => e.id === Number(this.elezione))?.soggetti?.area || [];
      },
      formato: formatoValore,

      async avvia() {
        if (this.indicatori.length) return;
        try {
          [this.indicatori, this.elezioni] = await Promise.all([
            json("/api/demografia/indicatori"),
            json("/api/elezioni"),
          ]);
        } catch (e) {
          this.errore = "Impossibile caricare gli indicatori: " + e.message;
          return;
        }
        const preferita = this.elezioni.find((e) => e.nome.startsWith("Comunali 2021 - 1"));
        this.elezione = (preferita || this.elezioni[this.elezioni.length - 1])?.id ?? null;
        await this.aggiorna();
      },

      async aggiorna() {
        await Promise.all([this.aggiornaMappa(), this.aggiornaScheda(), this.aggiornaDispersione()]);
      },

      async aggiornaMappa() {
        if (Alpine.store("selezione").modulo !== "demografia") return;
        try {
          const p = new URLSearchParams({ indicatore: this.indicatore, livello: this.livello });
          const r = await json(`/api/demografia/mappa?${p}`);
          this.errore = null;
          this.mappa = r;
          const valori = Object.fromEntries(r.valori.map((v) => [v.codice, v.valore]));
          const scala = Scala.classi(Object.values(valori), false);
          const formato = (v) => formatoValore(v, r.unita);
          this.legenda = Scala.legenda(scala, formato);
          await window.MappaTorino.colora(this.livello, valori, (v) => Scala.coloreDi(scala, v), formato);
        } catch (e) {
          this.errore = e.message;
          window.MappaTorino.pulisci();
        }
      },

      async aggiornaScheda() {
        if (Alpine.store("selezione").modulo !== "demografia") return;
        const area = Alpine.store("selezione").area;
        this.scheda = null;
        this.erroreScheda = null;
        if (!area) return;
        try {
          const p = new URLSearchParams({ livello: area.tipo, codice: area.codice });
          this.scheda = await json(`/api/demografia/area?${p}`);
        } catch (e) {
          this.erroreScheda = e.message;
          return;
        }
        await new Promise((ok) => Alpine.nextTick(ok));
        this.disegnaPiramide();
      },

      async aggiornaDispersione() {
        if (Alpine.store("selezione").modulo !== "demografia" || !this.elezione) return;
        if (!this.soggettiAree.includes(this.soggetto)) this.soggetto = this.soggettiAree[0] || "";
        const p = new URLSearchParams({
          indicatore: this.indicatore,
          elezione: this.elezione,
          soggetto: this.soggetto,
          tipo: "area",
          livello: this.livello,
        });
        try {
          this.dispersione = await json(`/api/demografia/dispersione?${p}`);
          this.erroreDispersione = null;
        } catch (e) {
          this.dispersione = null;
          this.erroreDispersione = e.message;
          return;
        }
        await new Promise((ok) => Alpine.nextTick(ok));
        this.disegnaDispersione();
      },

      disegnaPiramide() {
        const tela = document.getElementById("grafico-piramide");
        const p = this.scheda?.piramide;
        if (!tela || !p) return;
        if (graficoPiramide) graficoPiramide.destroy();
        // Classi dall'alto (anziani) al basso (bambini); maschi a sinistra (valori negativi).
        const classi = [...p.classi].reverse();
        const inv = (a) => [...a].reverse();
        graficoPiramide = new Chart(tela, {
          type: "bar",
          data: {
            labels: classi,
            datasets: [
              { label: "Maschi", data: inv(p.maschi).map((v) => -v), backgroundColor: COLORE_AREA, stack: "area" },
              { label: "Femmine", data: inv(p.femmine), backgroundColor: COLORE_CITTA, stack: "area" },
              {
                label: "Torino",
                data: inv(p.citta_maschi).map((v) => -v),
                backgroundColor: "rgba(0,0,0,0)",
                borderColor: "#1d2330",
                borderWidth: 1,
                stack: "citta",
              },
              {
                label: "Torino ",
                data: inv(p.citta_femmine),
                backgroundColor: "rgba(0,0,0,0)",
                borderColor: "#1d2330",
                borderWidth: 1,
                stack: "citta",
              },
            ],
          },
          options: {
            indexAxis: "y",
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                stacked: false,
                grid: { color: "#ecebe8" },
                border: { display: false },
                ticks: { color: "#5d6675", callback: (v) => `${Math.abs(v)}%` },
              },
              y: { stacked: true, grid: { display: false }, ticks: { color: "#1d2330", font: { size: 10 } } },
            },
            datasets: { bar: { categoryPercentage: 1, barPercentage: 0.9 } },
            plugins: {
              legend: {
                position: "top",
                align: "start",
                labels: {
                  boxWidth: 10,
                  boxHeight: 10,
                  color: "#1d2330",
                  filter: (voce) => voce.text !== "Torino ",
                },
              },
              tooltip: {
                callbacks: { label: (c) => `${c.dataset.label.trim()}: ${fmt(Math.abs(c.parsed.x))}%` },
              },
            },
          },
        });
      },

      disegnaDispersione() {
        const tela = document.getElementById("grafico-dispersione");
        const d = this.dispersione;
        if (!tela || !d) return;
        if (graficoDispersione) graficoDispersione.destroy();
        const selezionata = Alpine.store("selezione").area;
        const evidenzia = (pt) =>
          selezionata &&
          ((this.livello === "circoscrizione" && selezionata.tipo === "circoscrizione" && pt.codice === selezionata.codice) ||
            (this.livello === "sezione" && selezionata.tipo === "sezione" && pt.codice === selezionata.codice));
        const altri = d.punti.filter((p) => !evidenzia(p));
        const scelto = d.punti.filter(evidenzia);
        const unita = this.corrente?.unita;
        graficoDispersione = new Chart(tela, {
          type: "scatter",
          data: {
            datasets: [
              {
                label: this.livello === "sezione" ? "Sezioni" : "Circoscrizioni",
                data: altri.map((p) => ({ x: p.x, y: p.y, codice: p.codice })),
                backgroundColor: "rgba(42,120,214,0.55)",
                pointRadius: this.livello === "sezione" ? 3 : 6,
                pointHoverRadius: 8,
              },
              {
                label: "Area selezionata",
                data: scelto.map((p) => ({ x: p.x, y: p.y, codice: p.codice })),
                backgroundColor: COLORE_CITTA,
                borderColor: "#ffffff",
                borderWidth: 2,
                pointRadius: 8,
              },
            ],
          },
          options: {
            maintainAspectRatio: false,
            animation: false,
            scales: {
              x: {
                title: { display: true, text: `${d.indicatore.nome} (${unita})`, color: "#5d6675" },
                grid: { color: "#ecebe8" },
                ticks: { color: "#5d6675" },
              },
              y: {
                title: { display: true, text: `${d.soggetto} (% voti)`, color: "#5d6675" },
                grid: { color: "#ecebe8" },
                ticks: { color: "#5d6675", callback: (v) => `${v}%` },
              },
            },
            plugins: {
              legend: { display: scelto.length > 0, position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10 } },
              tooltip: {
                callbacks: {
                  label: (c) =>
                    `${this.livello === "sezione" ? "Sezione" : "Circoscrizione"} ${c.raw.codice}: ` +
                    `${formatoValore(c.raw.x, unita)}, ${fmt(c.raw.y)}% ${d.soggetto}`,
                },
              },
            },
          },
        });
      },
    });

    // Entrando nel modulo si colora la mappa; uscendo ci pensa il modulo successivo.
    Alpine.effect(() => {
      const modulo = Alpine.store("selezione").modulo;
      const s = Alpine.store("demografia");
      queueMicrotask(async () => {
        if (modulo !== "demografia") return;
        if (!s.indicatori.length) await s.avvia();
        else await s.aggiorna();
      });
    });

    Alpine.effect(() => {
      Alpine.store("selezione").area; // dipendenza
      const s = Alpine.store("demografia");
      queueMicrotask(async () => {
        if (Alpine.store("selezione").modulo !== "demografia" || !s.indicatori.length) return;
        await s.aggiornaScheda();
        s.disegnaDispersione();
      });
    });
  });
})();
