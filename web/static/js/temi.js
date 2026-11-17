// Modulo "Temi": matrice temi × circoscrizioni, mappa del tema scelto, andamento e articoli,
// classificazione via chat (scarica prompt, carica JSON). Per i social solo numeri aggregati.
(() => {
  const COLORI_SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]; // slot 1-5
  let graficoAndamento = null;

  async function json(url, opzioni) {
    const r = await fetch(url, opzioni);
    if (!r.ok) {
      let dettaglio = `HTTP ${r.status}`;
      try {
        dettaglio = (await r.json()).detail || dettaglio;
      } catch (_) {}
      throw new Error(typeof dettaglio === "string" ? dettaglio : JSON.stringify(dettaglio));
    }
    return r.json();
  }

  const fmtSentiment = (v) => (v === null || v === undefined ? "–" : (v > 0 ? "+" : "") + v.toFixed(1));

  document.addEventListener("alpine:init", () => {
    Alpine.store("temi", {
      settimane: 4,
      matrice: null,
      tema: "",
      stato: null,
      andamento: null,
      articoli: [],
      legenda: [],
      esitoImport: null,
      erroreImport: null,
      caricamentoImport: false,
      errore: null,
      circoscrizioni: ["1", "2", "3", "4", "5", "6", "7", "8"],
      scala: null,
      fmtSentiment,

      cella(tema, area) {
        return this.matrice?.celle.find((c) => c.tema === tema && c.area === area) || null;
      },
      coloreCella(tema, area) {
        const c = this.cella(tema, area);
        return c && this.scala ? Scala.coloreDi(this.scala, c.volume) : "transparent";
      },
      testoChiaro(tema, area) {
        // testo bianco sui tre gradini più scuri della rampa
        const c = this.cella(tema, area);
        if (!c || !this.scala) return false;
        return Scala.SEQUENZIALE.indexOf(Scala.coloreDi(this.scala, c.volume)) >= 3;
      },

      async avvia() {
        await this.aggiorna();
      },

      async aggiorna() {
        try {
          [this.stato, this.matrice] = await Promise.all([
            json("/api/temi/stato"),
            json(`/api/temi/matrice?settimane=${this.settimane}`),
          ]);
          this.errore = null;
        } catch (e) {
          this.errore = e.message;
          return;
        }
        const volumi = this.matrice.celle.map((c) => c.volume);
        this.scala = Scala.classi(volumi, false);
        if (!this.matrice.temi.includes(this.tema)) this.tema = this.matrice.temi[0] || "";
        await Promise.all([this.aggiornaMappa(), this.aggiornaDettaglio()]);
      },

      async aggiornaMappa() {
        if (Alpine.store("selezione").modulo !== "temi") return;
        if (!this.tema) {
          window.MappaTorino.pulisci();
          this.legenda = [];
          return;
        }
        const valori = Object.fromEntries(
          this.matrice.celle.filter((c) => c.tema === this.tema).map((c) => [c.area, c.volume]),
        );
        const scala = Scala.classi(Object.values(valori), false);
        const formato = (v) => `${Math.round(v)} documenti`;
        this.legenda = Scala.legenda(scala, formato);
        await window.MappaTorino.colora("circoscrizione", valori, (v) => Scala.coloreDi(scala, v), formato);
      },

      async aggiornaDettaglio() {
        if (Alpine.store("selezione").modulo !== "temi") return;
        const area = Alpine.store("selezione").area;
        const circ = area ? (area.tipo === "sezione" ? area.circoscrizione : area.codice) : "";
        const pA = new URLSearchParams({ settimane: Math.max(this.settimane, 8) });
        const pB = new URLSearchParams({ limite: 15 });
        if (circ) {
          pA.set("area", circ);
          pB.set("area", circ);
        }
        if (this.tema) pB.set("tema", this.tema);
        try {
          [this.andamento, this.articoli] = await Promise.all([
            json(`/api/temi/andamento?${pA}`),
            json(`/api/temi/articoli?${pB}`),
          ]);
        } catch (e) {
          this.errore = e.message;
          return;
        }
        await new Promise((ok) => Alpine.nextTick(ok));
        this.disegnaAndamento();
      },

      scegli(tema, area) {
        this.tema = tema;
        if (area) Alpine.store("mappa").selezionaCircoscrizione(area);
        else Alpine.store("selezione").azzera();
        this.aggiornaMappa();
        this.aggiornaDettaglio();
      },

      disegnaAndamento() {
        const tela = document.getElementById("grafico-andamento");
        if (!tela || !this.andamento) return;
        if (graficoAndamento) graficoAndamento.destroy();
        const etichette = this.andamento.settimane.map((s) =>
          new Date(s).toLocaleDateString("it-IT", { day: "numeric", month: "short" }),
        );
        graficoAndamento = new Chart(tela, {
          type: "line",
          data: {
            labels: etichette,
            datasets: this.andamento.serie.map((s, i) => ({
              label: s.tema,
              data: s.volumi,
              borderColor: COLORI_SERIE[i],
              backgroundColor: COLORI_SERIE[i],
              borderWidth: 2,
              pointRadius: 2,
              tension: 0.2,
            })),
          },
          options: {
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: "index", intersect: false },
            scales: {
              y: { beginAtZero: true, grid: { color: "#ecebe8" }, ticks: { color: "#5d6675", precision: 0 } },
              x: { grid: { display: false }, ticks: { color: "#5d6675", font: { size: 10 } } },
            },
            plugins: {
              legend: { position: "bottom", align: "start", labels: { boxWidth: 10, boxHeight: 10, font: { size: 10 } } },
            },
          },
        });
      },

      async caricaJson(evento) {
        const file = evento.target.files?.[0];
        if (!file) return;
        this.caricamentoImport = true;
        this.esitoImport = null;
        this.erroreImport = null;
        try {
          const testo = await file.text();
          this.esitoImport = await json("/api/temi/classificazioni", {
            method: "POST",
            headers: { "Content-Type": "text/plain" },
            body: testo,
          });
          await this.aggiorna();
        } catch (e) {
          this.erroreImport = e.message;
        } finally {
          this.caricamentoImport = false;
          evento.target.value = "";
        }
      },
    });

    Alpine.effect(() => {
      const modulo = Alpine.store("selezione").modulo;
      const s = Alpine.store("temi");
      queueMicrotask(() => {
        if (modulo === "temi") s.avvia();
      });
    });

    Alpine.effect(() => {
      Alpine.store("selezione").area; // dipendenza
      const s = Alpine.store("temi");
      queueMicrotask(() => {
        if (Alpine.store("selezione").modulo === "temi" && s.matrice) s.aggiornaDettaglio();
      });
    });
  });
})();
