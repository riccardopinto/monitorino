// Modulo "Storico elettorale": filtri, coropletica, dettaglio dell'area, confronti e flussi.
(() => {
  // Rampa sequenziale blu (quote, affluenza, voti) e scala divergente rosso-grigio-blu
  // (variazioni), dalla palette di riferimento: chiaro = poco, scuro = tanto.
  const SEQUENZIALE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
  const DIVERGENTE = ["#a82c2b", "#e34948", "#f3a9a8", "#f0efec", "#9ec5f4", "#3987e5", "#184f95"];
  const COLORE_AREA = "#2a78d6"; // slot 1
  const COLORE_CONFRONTO = "#eb6834"; // slot 2

  const NOMI_TIPO = {
    area: "Aree politiche",
    forza: "Forze politiche",
    lista: "Liste",
    candidato: "Candidati",
  };
  const NOMI_METRICA = {
    quota: "Quota %",
    voti: "Voti",
    affluenza: "Affluenza %",
    variazione: "Variazione (punti)",
  };

  const fmt = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 1 });
  const fmtInt = new Intl.NumberFormat("it-IT");

  let grafico = null;

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

  function classi(valori, divergente) {
    // Limiti delle classi: per le variazioni simmetrici intorno a zero.
    const numeri = valori.filter((v) => v !== null && v !== undefined);
    if (!numeri.length) return { limiti: [], colori: [] };
    if (divergente) {
      const m = Math.max(...numeri.map(Math.abs)) || 1;
      const passo = m / 3.5;
      const limiti = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((k) => k * passo);
      return { limiti, colori: DIVERGENTE };
    }
    const min = Math.min(...numeri);
    const max = Math.max(...numeri);
    const n = SEQUENZIALE.length;
    const passo = (max - min) / n || 1;
    const limiti = Array.from({ length: n - 1 }, (_, i) => min + passo * (i + 1));
    return { limiti, colori: SEQUENZIALE, min, max };
  }

  function coloreDi(scala, v) {
    let i = 0;
    while (i < scala.limiti.length && v >= scala.limiti[i]) i++;
    return scala.colori[i];
  }

  document.addEventListener("alpine:init", () => {
    Alpine.store("storico", {
      NOMI_TIPO,
      NOMI_METRICA,
      elezioni: [],
      elezione: null, // id
      confronto: "", // id dell'elezione di partenza per variazione e flussi ("" = nessuna)
      livello: "circoscrizione",
      tipo: "area",
      soggetto: "",
      metrica: "quota",
      legenda: [],
      unita: "%",
      citta: null,
      dettaglio: null,
      dettaglioConfronto: null,
      areaConfronto: "", // codice di una seconda circoscrizione da affiancare
      flussi: null,
      erroreFlussi: null,
      errore: null,
      caricamento: false,

      get corrente() {
        return this.elezioni.find((e) => e.id === Number(this.elezione)) || null;
      },
      get tipiDisponibili() {
        return Object.keys(this.corrente?.soggetti || {});
      },
      get soggettiDisponibili() {
        return this.corrente?.soggetti?.[this.tipo] || [];
      },
      get nomeConfronto() {
        return this.elezioni.find((e) => e.id === Number(this.confronto))?.nome || "";
      },

      async avvia() {
        if (this.elezioni.length) return;
        try {
          this.elezioni = await json("/api/elezioni");
        } catch (e) {
          this.errore = "Impossibile caricare le elezioni: " + e.message;
          return;
        }
        const preferita = this.elezioni.find((e) => e.nome.startsWith("Comunali 2021 - 1"));
        this.elezione = (preferita || this.elezioni[this.elezioni.length - 1])?.id ?? null;
        this.adattaFiltri();
        await this.aggiorna();
      },

      adattaFiltri() {
        if (!this.tipiDisponibili.includes(this.tipo)) this.tipo = this.tipiDisponibili[0] || "area";
        if (!this.soggettiDisponibili.includes(this.soggetto)) this.soggetto = this.soggettiDisponibili[0] || "";
        if (Number(this.confronto) === Number(this.elezione)) this.confronto = "";
        if (this.metrica === "variazione" && !this.confronto) this.metrica = "quota";
      },

      async cambia() {
        this.adattaFiltri();
        await this.aggiorna();
      },

      async aggiorna() {
        await Promise.all([this.aggiornaMappa(), this.aggiornaDettaglio()]);
      },

      async aggiornaMappa() {
        if (!this.elezione || Alpine.store("selezione").modulo !== "storico") return;
        const p = new URLSearchParams({
          livello: this.livello,
          metrica: this.metrica,
          tipo: this.tipo,
        });
        if (this.metrica !== "affluenza") p.set("soggetto", this.soggetto);
        if (this.metrica === "variazione") p.set("confronto", this.confronto);
        this.caricamento = true;
        try {
          const r = await json(`/api/elezioni/${this.elezione}/mappa?${p}`);
          this.errore = null;
          const valori = Object.fromEntries(r.valori.map((v) => [v.codice, v.valore]));
          const scala = classi(Object.values(valori), r.metrica === "variazione");
          const unita = r.unita;
          const formato = (v) =>
            unita === "voti"
              ? `${fmtInt.format(v)} voti`
              : unita === "punti"
                ? `${v > 0 ? "+" : ""}${fmt.format(v)} punti`
                : `${fmt.format(v)}%`;
          this.unita = unita;
          this.citta = r.citta;
          this.legenda = scala.colori.map((colore, i) => {
            const da = i === 0 ? null : scala.limiti[i - 1];
            const a = i < scala.limiti.length ? scala.limiti[i] : null;
            const testo =
              da === null ? `meno di ${formato(a)}` : a === null ? `da ${formato(da)}` : `${formato(da)} – ${formato(a)}`;
            return { colore, testo };
          });
          if (!scala.limiti.length) this.legenda = [];
          await window.MappaTorino.colora(this.livello, valori, (v) => coloreDi(scala, v), formato);
        } catch (e) {
          this.errore = e.message;
          window.MappaTorino.pulisci();
        } finally {
          this.caricamento = false;
        }
      },

      parametriArea() {
        const area = Alpine.store("selezione").area;
        if (!area) return { livello: "citta", codice: "Torino", nome: "Torino" };
        return { livello: area.tipo, codice: area.codice, nome: area.tipo === "sezione" ? area.nome : `Circoscrizione ${area.codice}` };
      },

      async aggiornaDettaglio() {
        if (!this.elezione || Alpine.store("selezione").modulo !== "storico") return;
        const { livello, codice } = this.parametriArea();
        const base = new URLSearchParams({ livello, codice, tipo: this.tipo });
        try {
          this.dettaglio = await json(`/api/elezioni/${this.elezione}/area?${base}`);
        } catch (e) {
          this.dettaglio = null;
          this.errore = e.message;
        }
        // Confronto: stessa area in un'altra elezione, oppure un'altra circoscrizione.
        this.dettaglioConfronto = null;
        try {
          if (this.confronto) {
            this.dettaglioConfronto = {
              etichetta: this.nomeConfronto,
              dati: await json(`/api/elezioni/${this.confronto}/area?${base}`),
            };
          } else if (this.areaConfronto && this.areaConfronto !== codice) {
            const p = new URLSearchParams({ livello: "circoscrizione", codice: this.areaConfronto, tipo: this.tipo });
            this.dettaglioConfronto = {
              etichetta: `Circoscrizione ${this.areaConfronto}`,
              dati: await json(`/api/elezioni/${this.elezione}/area?${p}`),
            };
          }
        } catch (e) {
          this.dettaglioConfronto = { etichetta: "", errore: e.message, dati: null };
        }
        // Il canvas sta dentro un x-if: esiste solo dopo il prossimo aggiornamento del DOM.
        await new Promise((ok) => Alpine.nextTick(ok));
        this.disegnaGrafico();
        await this.aggiornaFlussi();
      },

      async aggiornaFlussi() {
        this.flussi = null;
        this.erroreFlussi = null;
        if (!this.confronto) return;
        const area = Alpine.store("selezione").area;
        const p = new URLSearchParams({ da: this.confronto, a: this.elezione });
        if (area) p.set("circoscrizione", area.tipo === "sezione" ? area.circoscrizione : area.codice);
        try {
          this.flussi = await json(`/api/flussi?${p}`);
        } catch (e) {
          this.erroreFlussi = e.message;
        }
      },

      disegnaGrafico() {
        const tela = document.getElementById("grafico-storico");
        if (!tela || !this.dettaglio) return;
        // Al massimo 12 soggetti (i più votati nell'area): il resto è nella tabella.
        const righe = this.dettaglio.righe.slice(0, 12);
        const etichette = righe.map((r) => r.soggetto);
        const conf = this.dettaglioConfronto?.dati;
        const perSoggetto = conf ? Object.fromEntries(conf.righe.map((r) => [r.soggetto, r.quota])) : null;
        const { nome } = this.parametriArea();
        const datasets = [
          { label: nome, data: righe.map((r) => r.quota), backgroundColor: COLORE_AREA },
          conf
            ? {
                label: this.dettaglioConfronto.etichetta,
                data: etichette.map((s) => perSoggetto[s] ?? 0),
                backgroundColor: COLORE_CONFRONTO,
              }
            : nome === "Torino"
              ? null
              : { label: "Media cittadina", data: righe.map((r) => r.quota_citta), backgroundColor: COLORE_CONFRONTO },
        ].filter(Boolean);
        if (grafico) grafico.destroy();
        tela.parentElement.style.height = `${Math.max(160, etichette.length * (datasets.length * 14 + 12) + 60)}px`;
        grafico = new Chart(tela, {
          type: "bar",
          data: { labels: etichette, datasets },
          options: {
            indexAxis: "y",
            maintainAspectRatio: false,
            animation: false,
            datasets: { bar: { borderRadius: 4, borderSkipped: "start", categoryPercentage: 0.8, barPercentage: 0.9 } },
            scales: {
              x: {
                beginAtZero: true,
                grid: { color: "#ecebe8" },
                border: { display: false },
                ticks: { color: "#5d6675", callback: (v) => `${v}%` },
              },
              y: { grid: { display: false }, ticks: { color: "#1d2330", autoSkip: false, font: { size: 11 } } },
            },
            plugins: {
              legend: { display: datasets.length > 1, position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10, color: "#1d2330" } },
              tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt.format(c.parsed.x)}%` } },
            },
          },
        });
      },
    });

    // Entrando nel modulo si colora la mappa; uscendo si toglie la coropletica.
    Alpine.effect(() => {
      const modulo = Alpine.store("selezione").modulo;
      const s = Alpine.store("storico");
      queueMicrotask(async () => {
        if (modulo !== "storico") {
          window.MappaTorino?.pulisci();
          return;
        }
        if (!s.elezioni.length) await s.avvia();
        else await s.aggiorna();
      });
    });

    // Cambiando l'area selezionata si aggiorna solo il pannello dettagli.
    Alpine.effect(() => {
      Alpine.store("selezione").area; // dipendenza
      const s = Alpine.store("storico");
      queueMicrotask(() => {
        if (Alpine.store("selezione").modulo === "storico" && s.elezioni.length) s.aggiornaDettaglio();
      });
    });
  });

  window.formatoNumero = (v, cifre = 1) =>
    v === null || v === undefined ? "–" : new Intl.NumberFormat("it-IT", { maximumFractionDigits: cifre }).format(v);
})();
