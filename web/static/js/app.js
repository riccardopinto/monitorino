// Stato condiviso dell'interfaccia. Ogni modulo legge l'area selezionata da $store.selezione.
document.addEventListener("alpine:init", () => {
  Alpine.store("selezione", {
    moduli: [
      { id: "mappa", nome: "Mappa" },
      { id: "storico", nome: "Storico elettorale" },
      { id: "demografia", nome: "Demografia" },
      { id: "temi", nome: "Temi" },
      { id: "laboratorio", nome: "Laboratorio messaggi" },
      { id: "studio", nome: "Studio contenuti" },
      { id: "report", nome: "Report" },
    ],
    modulo: "mappa",
    // { tipo: "circoscrizione" | "sezione", codice: "3", nome: "Circoscrizione 3" } oppure null
    area: null,

    nomeModulo() {
      return this.moduli.find((m) => m.id === this.modulo)?.nome ?? "";
    },
    seleziona(area) {
      this.area = area;
    },
    azzera() {
      this.area = null;
    },
  });

  Alpine.store("stato", {
    versione: null,
    datiDiProva: false,
    errore: null,

    async carica() {
      try {
        const risposta = await fetch("/api/stato");
        if (!risposta.ok) throw new Error(`HTTP ${risposta.status}`);
        const dati = await risposta.json();
        this.versione = dati.versione;
        this.datiDiProva = dati.dati_di_prova;
        this.errore = dati.schema_completo ? null : "Schema del database incompleto";
      } catch (e) {
        this.errore = "Server non raggiungibile: " + e.message;
      }
    },
  });

  Alpine.store("stato").carica();
});
