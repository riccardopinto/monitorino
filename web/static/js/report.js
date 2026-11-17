// Report PDF: pulsante "Esporta PDF" (tipo e parametri presi dalla vista corrente), pannello di
// anteprima con le opzioni, generazione del PDF e archivio nel modulo "Report".
(() => {
  const BASE = "/api/report";
  const CHIAVE_AUTORE = "monitorino.autoreReport";

  async function json(url, opzioni) {
    const r = await fetch(url, opzioni);
    if (!r.ok) {
      let dettaglio = `HTTP ${r.status}`;
      try {
        dettaglio = (await r.json()).detail || dettaglio;
      } catch (_) {}
      throw new Error(typeof dettaglio === "string" ? dettaglio : JSON.stringify(dettaglio));
    }
    return r;
  }

  function leggiAutore() {
    try {
      return localStorage.getItem(CHIAVE_AUTORE) || "";
    } catch (_) {
      return "";
    }
  }

  function circSelezionata() {
    const a = Alpine.store("selezione").area;
    if (!a) return null;
    return a.tipo === "sezione" ? a.circoscrizione : a.codice;
  }

  document.addEventListener("alpine:init", () => {
    Alpine.store("report", {
      aperto: false,
      opzioni: null, // /api/report/tipi
      tipo: "scheda",
      p: {},
      titolo: "",
      autore: leggiAutore(),
      html: "",
      errore: null,
      occupato: false,
      esito: null,
      archivio: [],
      erroreArchivio: null,
      circoscrizioni: ["1", "2", "3", "4", "5", "6", "7", "8"],

      async caricaOpzioni() {
        if (this.opzioni) return;
        this.opzioni = await (await json(`${BASE}/tipi`)).json();
        if (this.opzioni.circoscrizioni.length) this.circoscrizioni = this.opzioni.circoscrizioni.map((c) => c.codice);
      },

      // Tipo e parametri suggeriti dalla vista corrente.
      dallaVista() {
        const modulo = Alpine.store("selezione").modulo;
        const circ = circSelezionata();
        if (modulo === "storico") {
          const s = Alpine.store("storico");
          if (s.confronto) {
            return ["confronto", { modo: "elezioni", da: Number(s.confronto), a: s.elezione, area: circ || "Torino" }];
          }
          return ["scheda", { area: circ || this.circoscrizioni[0] }];
        }
        if (modulo === "temi") return ["bollettino", { settimana: "" }];
        if (modulo === "laboratorio") {
          const run = Alpine.store("lab").run;
          if (run?.stato === "completata") return ["simulazione", { simulazione: run.id }];
          return ["simulazione", { simulazione: this.opzioni?.simulazioni[0]?.id ?? "" }];
        }
        return ["scheda", { area: circ || this.circoscrizioni[0] }];
      },

      async apri(tipo, parametri) {
        this.errore = null;
        this.esito = null;
        this.titolo = "";
        try {
          await this.caricaOpzioni();
        } catch (e) {
          this.errore = e.message;
        }
        const [t, p] = tipo ? [tipo, parametri || {}] : this.dallaVista();
        this.tipo = t;
        this.p = { ...this.predefiniti(t), ...p };
        this.aperto = true;
        await this.anteprima();
      },

      chiudi() {
        this.aperto = false;
        this.html = "";
      },

      predefiniti(tipo) {
        const el = this.opzioni?.elezioni || [];
        const ultima = el[el.length - 1]?.id;
        const c = this.circoscrizioni;
        const [a1, a2] = c.includes("3") && c.includes("4") ? ["3", "4"] : [c[0], c[1]];
        return {
          scheda: { area: c[0] },
          confronto: { modo: "elezioni", da: el[el.length - 2]?.id, a: ultima, area: "Torino", elezione: ultima, area1: a1, area2: a2 },
          bollettino: { settimana: "" },
          simulazione: { simulazione: this.opzioni?.simulazioni[0]?.id ?? "" },
          kit: { candidato: "sindaco", dal: "", al: "" },
        }[tipo];
      },

      cambiaTipo() {
        this.p = this.predefiniti(this.tipo);
        this.titolo = "";
        this.anteprima();
      },

      corpo() {
        const p = { ...this.p };
        for (const k of ["da", "a", "elezione", "simulazione"]) if (p[k] !== undefined && p[k] !== "") p[k] = Number(p[k]);
        for (const k of Object.keys(p)) if (p[k] === "" || p[k] === null || p[k] === undefined) delete p[k];
        return { tipo: this.tipo, parametri: p, titolo: this.titolo, autore: this.autore };
      },

      async anteprima() {
        this.occupato = true;
        this.errore = null;
        try {
          const r = await json(`${BASE}/anteprima`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this.corpo()),
          });
          this.html = await r.text();
        } catch (e) {
          this.html = "";
          this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },

      async genera() {
        this.occupato = true;
        this.errore = null;
        this.esito = null;
        try {
          localStorage.setItem(CHIAVE_AUTORE, this.autore);
        } catch (_) {}
        try {
          const esito = await (await json(BASE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this.corpo()),
          })).json();
          this.esito = esito;
          const a = document.createElement("a");
          a.href = esito.url;
          a.download = esito.file;
          document.body.appendChild(a);
          a.click();
          a.remove();
          this.caricaArchivio();
        } catch (e) {
          this.errore = e.message;
        } finally {
          this.occupato = false;
        }
      },

      async caricaArchivio() {
        try {
          this.archivio = (await (await json(BASE)).json()).report;
          this.erroreArchivio = null;
        } catch (e) {
          this.erroreArchivio = e.message;
        }
      },

      nomeCirc(codice) {
        return this.opzioni?.circoscrizioni.find((c) => c.codice === codice)?.nome || "";
      },

      descriviParametri(r) {
        const p = r.parametri || {};
        if (r.tipo === "scheda") return `circoscrizione ${p.area}`;
        if (r.tipo === "confronto") return p.modo === "aree" ? `circ. ${p.area1} e ${p.area2}` : `${p.area || "Torino"}`;
        if (r.tipo === "simulazione") return `simulazione ${p.simulazione}`;
        if (r.tipo === "kit") return p.candidato;
        return p.settimana || "ultima settimana";
      },
    });

    Alpine.effect(() => {
      const modulo = Alpine.store("selezione").modulo;
      queueMicrotask(() => {
        if (modulo === "report") {
          Alpine.store("report").caricaArchivio();
          Alpine.store("report").caricaOpzioni().catch(() => {});
          window.MappaTorino?.pulisci();
        }
      });
    });
  });
})();
