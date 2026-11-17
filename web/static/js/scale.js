// Scale di colore e legende condivise dai moduli con coropletica.
// Sequenziale a più tinte ad alto contrasto (viridis: giallo chiaro = poco, viola scuro = tanto):
// la luminosità scende in modo regolare, quindi resta leggibile anche con daltonismo e in
// bianco e nero. Divergente rosso-grigio-blu (ColorBrewer RdBu) per variazioni e saldi.
(() => {
  const SEQUENZIALE = ["#fde725", "#7ad151", "#22a884", "#2a788e", "#414487", "#440154"];
  const DIVERGENTE = ["#b2182b", "#ef8a62", "#fddbc7", "#ededed", "#d1e5f0", "#67a9cf", "#2166ac"];
  // Indice del primo gradino su cui serve testo bianco.
  const PRIMO_SCURO = 3;

  // Valori interi distinti se sono conteggi con pochi valori: una classe per valore.
  function valoriInteri(numeri) {
    if (!numeri.length || numeri.some((v) => !Number.isInteger(v))) return null;
    const lo = Math.min(...numeri);
    const hi = Math.max(...numeri);
    if (hi - lo >= SEQUENZIALE.length) return null;
    return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  }

  // Divergente: simmetrica intorno allo zero se i segni sono misti; con valori tutti dello
  // stesso segno solo il ramo di quel segno, con classi tra minimo e massimo.
  // Sequenziale: intervalli uguali; per conteggi con pochi valori, una classe per valore.
  function classi(valori, divergente) {
    const numeri = valori.filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
    if (!numeri.length) return { limiti: [], colori: [] };
    const min = Math.min(...numeri);
    const max = Math.max(...numeri);
    if (divergente) {
      if ((min >= 0 && max > 0) || (max <= 0 && min < 0)) {
        const passo = (max - min) / 3 || 1;
        return { limiti: [min + passo, min + 2 * passo], colori: min >= 0 ? DIVERGENTE.slice(4) : DIVERGENTE.slice(0, 3) };
      }
      const m = Math.max(...numeri.map(Math.abs)) || 1;
      const passo = m / 3.5;
      return { limiti: [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((k) => k * passo), colori: DIVERGENTE };
    }
    const n = SEQUENZIALE.length;
    const interi = valoriInteri(numeri);
    if (interi) {
      const k = interi.length;
      const colori = k > 1 ? interi.map((_, i) => SEQUENZIALE[Math.round((i * (n - 1)) / (k - 1))]) : [SEQUENZIALE[2]];
      return { limiti: interi.slice(1), colori, interi };
    }
    const passo = (max - min) / n || 1;
    return { limiti: Array.from({ length: n - 1 }, (_, i) => min + passo * (i + 1)), colori: SEQUENZIALE };
  }

  function coloreDi(scala, v) {
    let i = 0;
    while (i < scala.limiti.length && v >= scala.limiti[i]) i++;
    return scala.colori[i];
  }

  function legenda(scala, formato) {
    if (!scala.limiti.length) return [];
    return scala.colori.map((colore, i) => {
      if (scala.interi) return { colore, testo: formato(scala.interi[i]) };
      const da = i === 0 ? null : scala.limiti[i - 1];
      const a = i < scala.limiti.length ? scala.limiti[i] : null;
      const testo =
        da === null ? `meno di ${formato(a)}` : a === null ? `da ${formato(da)}` : `${formato(da)} – ${formato(a)}`;
      return { colore, testo };
    });
  }

  window.Scala = { SEQUENZIALE, DIVERGENTE, PRIMO_SCURO, classi, coloreDi, legenda };
})();
