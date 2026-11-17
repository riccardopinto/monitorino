// Modulo mappa: Leaflet con i livelli circoscrizioni e sezioni.
// La selezione vive in $store.selezione, condivisa da tutti i moduli; la mappa la legge
// e la scrive. Gli oggetti Leaflet restano fuori dagli store Alpine (niente proxy reattivi).
// Gli altri moduli colorano la mappa con window.MappaTorino.colora(...) (coropletica).
(() => {
  const CENTRO_TORINO = [45.07, 7.68];
  const BORDO = { circoscrizione: "#1f5fa8", sezione: "#475569" };
  const STILI = {
    circoscrizione: { color: BORDO.circoscrizione, weight: 2, opacity: 0.9, fillColor: "#1f5fa8", fillOpacity: 0.06 },
    sezione: { color: BORDO.sezione, weight: 0.7, opacity: 0.8, fillColor: "#475569", fillOpacity: 0.02 },
  };
  const SELEZIONE = { color: "#c2410c", weight: 3, opacity: 1 };

  let mappa = null;
  let sfondo = null;
  const livelli = {}; // tipo -> L.GeoJSON
  const perId = new Map(); // id area -> { layer, tipo, props }
  let evidenziato = null;
  // Coropletica attiva: { tipo, valori: {codice: numero}, colore: fn(v) -> hex, formato: fn(v) -> testo }
  let colorazione = null;
  // Pallini sulle etichette delle circoscrizioni: {codice: { testo, nuovo, titolo }}
  let segnali = {};

  function escapa(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  function etichetta(codice) {
    const s = segnali[codice];
    if (!s) return `<strong>${codice}</strong>`;
    const classe = s.nuovo ? "pallino nuovo" : "pallino";
    return `<strong>${codice}</strong><span class="${classe}" title="${escapa(s.titolo || "")}">${escapa(s.testo)}</span>`;
  }

  function aggiornaEtichette() {
    if (!livelli.circoscrizione) return;
    livelli.circoscrizione.eachLayer((layer) => {
      layer.setTooltipContent(etichetta(layer.feature.properties.codice));
    });
  }

  async function caricaGeojson(tipo) {
    const risposta = await fetch(`/api/aree?tipo=${tipo}`);
    if (!risposta.ok) throw new Error(`HTTP ${risposta.status}`);
    return risposta.json();
  }

  function seleziona(p) {
    Alpine.store("selezione").seleziona({
      id: p.id,
      tipo: p.tipo,
      codice: p.codice,
      nome: p.nome,
      circoscrizione: p.circoscrizione,
      approssimata: p.approssimata,
    });
  }

  function valore(tipo, codice) {
    if (!colorazione || colorazione.tipo !== tipo) return undefined;
    return colorazione.valori[codice];
  }

  function stile(tipo, props) {
    const base = { ...STILI[tipo] };
    if (colorazione) {
      if (colorazione.tipo === tipo) {
        const v = valore(tipo, props.codice);
        base.fillColor = v === undefined || v === null ? "#d9d9d6" : colorazione.colore(v);
        base.fillOpacity = 0.85;
        if (tipo === "sezione") base.color = "#ffffff";
      } else {
        base.fillOpacity = 0; // l'altro livello resta solo come contorno
      }
    }
    if (evidenziato && evidenziato.props.id === props.id) Object.assign(base, SELEZIONE);
    return base;
  }

  function testoValore(tipo, codice) {
    const v = valore(tipo, codice);
    if (v === undefined) return "";
    return `<br><strong>${v === null ? "n.d." : colorazione.formato(v)}</strong>`;
  }

  function creaLivello(tipo, dati) {
    return L.geoJSON(dati, {
      style: (f) => stile(tipo, f.properties),
      onEachFeature: (f, layer) => {
        const p = f.properties;
        perId.set(p.id, { layer, tipo, props: p });
        if (tipo === "circoscrizione") {
          layer.bindTooltip(etichetta(p.codice), {
            permanent: true,
            direction: "center",
            className: "etichetta-circoscrizione",
          });
          // Nome completo e valore al passaggio del mouse; autoPan spento per non spostare la mappa.
          layer.bindPopup(() => `Circoscrizione ${p.codice}<br>${p.nome}${testoValore(tipo, p.codice)}`, {
            closeButton: false,
            autoPan: false,
          });
          layer.on("mouseover", (e) => layer.openPopup(e.latlng));
          layer.on("mouseout", () => layer.closePopup());
        } else {
          layer.bindTooltip(() => `Sezione ${p.codice}${testoValore(tipo, p.codice)}`, {
            sticky: true,
            className: "etichetta-sezione",
          });
        }
        layer.on("click", () => seleziona(p));
      },
    });
  }

  function ridisegna() {
    for (const [tipo, livello] of Object.entries(livelli)) {
      livello.eachLayer((layer) => layer.setStyle(stile(tipo, layer.feature.properties)));
    }
    if (evidenziato && mappa.hasLayer(evidenziato.layer)) evidenziato.layer.bringToFront();
  }

  function evidenzia(area) {
    evidenziato = area ? perId.get(area.id) || null : null;
    ridisegna();
  }

  async function avvia(elemento) {
    const statoMappa = Alpine.store("mappa");
    mappa = L.map(elemento, { zoomSnap: 0.5 }).setView(CENTRO_TORINO, 12);

    // Lo sfondo dipende da MAPPA_SFONDO, letto da /api/stato.
    Alpine.effect(() => {
      if (Alpine.store("stato").mappaSfondo === "osm" && !sfondo) {
        sfondo = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        }).addTo(mappa);
      }
    });

    try {
      const dati = await caricaGeojson("circoscrizione");
      statoMappa.nomiCircoscrizioni = Object.fromEntries(
        dati.features.map((f) => [f.properties.codice, f.properties.nome]),
      );
      statoMappa.idCircoscrizioni = Object.fromEntries(
        dati.features.map((f) => [f.properties.codice, f.properties.id]),
      );
      livelli.circoscrizione = creaLivello("circoscrizione", dati).addTo(mappa);
      if (dati.features.length) mappa.fitBounds(livelli.circoscrizione.getBounds(), { padding: [12, 12] });
      else statoMappa.errore = "Nessuna circoscrizione nel database: eseguire app.ingest.circoscrizioni";
      statoMappa.pronta = true;
    } catch (e) {
      statoMappa.errore = "Impossibile caricare le circoscrizioni: " + e.message;
    }

    Alpine.effect(() => evidenzia(Alpine.store("selezione").area));
  }

  async function mostraSezioni(visibili) {
    const statoMappa = Alpine.store("mappa");
    if (!mappa) return;
    if (visibili && !livelli.sezione) {
      statoMappa.caricamento = true;
      try {
        livelli.sezione = creaLivello("sezione", await caricaGeojson("sezione"));
      } catch (e) {
        statoMappa.errore = "Impossibile caricare le sezioni: " + e.message;
        statoMappa.sezioniVisibili = false;
        return;
      } finally {
        statoMappa.caricamento = false;
      }
    }
    if (!livelli.sezione) return;
    if (visibili) livelli.sezione.addTo(mappa);
    else {
      livelli.sezione.remove();
      const area = Alpine.store("selezione").area;
      if (area?.tipo === "sezione") Alpine.store("selezione").azzera();
    }
    evidenzia(Alpine.store("selezione").area);
  }

  // API per gli altri moduli.
  window.MappaTorino = {
    async colora(tipo, valori, colore, formato) {
      if (tipo === "sezione" && !Alpine.store("mappa").sezioniVisibili) {
        Alpine.store("mappa").sezioniVisibili = true;
        await mostraSezioni(true);
      }
      colorazione = { tipo, valori, colore, formato };
      ridisegna();
    },
    pulisci() {
      if (!colorazione) return;
      colorazione = null;
      ridisegna();
    },
    segnala(valori) {
      segnali = valori || {};
      aggiornaEtichette();
    },
    togliSegnali() {
      if (!Object.keys(segnali).length) return;
      segnali = {};
      aggiornaEtichette();
    },
  };

  document.addEventListener("alpine:init", () => {
    Alpine.store("mappa", {
      pronta: false,
      sezioniVisibili: false,
      caricamento: false,
      errore: null,
      nomiCircoscrizioni: {},
      idCircoscrizioni: {},
      selezionaCircoscrizione(codice) {
        Alpine.store("selezione").seleziona({
          id: this.idCircoscrizioni[codice],
          tipo: "circoscrizione",
          codice,
          nome: this.nomiCircoscrizioni[codice],
          circoscrizione: codice,
          approssimata: false,
        });
      },
      alternaSezioni() {
        mostraSezioni(this.sezioniVisibili);
      },
    });

    Alpine.data("mappaTorino", () => ({
      init() {
        avvia(this.$el);
      },
    }));
  });
})();
