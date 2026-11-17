// Modulo mappa: Leaflet con i livelli circoscrizioni e sezioni.
// La selezione vive in $store.selezione, condivisa da tutti i moduli; la mappa la legge
// e la scrive. Gli oggetti Leaflet restano fuori dagli store Alpine (niente proxy reattivi).
(() => {
  const CENTRO_TORINO = [45.07, 7.68];
  const STILI = {
    circoscrizione: { color: "#1f5fa8", weight: 2, opacity: 0.9, fillColor: "#1f5fa8", fillOpacity: 0.06 },
    sezione: { color: "#475569", weight: 0.7, opacity: 0.8, fillColor: "#475569", fillOpacity: 0.02 },
    selezionata: { color: "#c2410c", weight: 3, opacity: 1, fillColor: "#f97316", fillOpacity: 0.25 },
  };

  let mappa = null;
  let sfondo = null;
  const livelli = {}; // tipo -> L.GeoJSON
  const perId = new Map(); // id area -> layer Leaflet
  let evidenziato = null;

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

  function creaLivello(tipo, dati) {
    return L.geoJSON(dati, {
      style: () => STILI[tipo],
      onEachFeature: (f, layer) => {
        const p = f.properties;
        perId.set(p.id, layer);
        if (tipo === "circoscrizione") {
          layer.bindTooltip(`<strong>${p.codice}</strong>`, {
            permanent: true,
            direction: "center",
            className: "etichetta-circoscrizione",
          });
          // Nome completo al passaggio del mouse; autoPan spento per non spostare la mappa.
          layer.bindPopup(`Circoscrizione ${p.codice}<br>${p.nome}`, {
            closeButton: false,
            autoPan: false,
          });
          layer.on("mouseover", (e) => layer.openPopup(e.latlng));
          layer.on("mouseout", () => layer.closePopup());
        } else {
          layer.bindTooltip(`Sezione ${p.codice}`, { sticky: true, className: "etichetta-sezione" });
        }
        layer.on("click", () => seleziona(p));
      },
    });
  }

  function evidenzia(area) {
    if (evidenziato) {
      evidenziato.layer.setStyle(STILI[evidenziato.tipo]);
      evidenziato = null;
    }
    if (!area) return;
    const layer = perId.get(area.id);
    if (!layer || !mappa.hasLayer(layer)) return;
    layer.setStyle(STILI.selezionata);
    layer.bringToFront();
    evidenziato = { layer, tipo: area.tipo };
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
      livelli.circoscrizione = creaLivello("circoscrizione", dati).addTo(mappa);
      if (dati.features.length) mappa.fitBounds(livelli.circoscrizione.getBounds(), { padding: [12, 12] });
      else statoMappa.errore = "Nessuna circoscrizione nel database: eseguire app.ingest.circoscrizioni";
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

  document.addEventListener("alpine:init", () => {
    Alpine.store("mappa", {
      sezioniVisibili: false,
      caricamento: false,
      errore: null,
      nomiCircoscrizioni: {},
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
