// Scale di colore e legende condivise dai moduli con coropletica.
// Sequenziale a più tinte ad alto contrasto (viridis: giallo chiaro = poco, viola scuro = tanto):
// la luminosità scende in modo regolare, quindi resta leggibile anche con daltonismo e in
// bianco e nero. Divergente rosso-grigio-blu (ColorBrewer RdBu) per variazioni e saldi.
(() => {
  const SEQUENZIALE = ["#fde725", "#7ad151", "#22a884", "#2a788e", "#414487", "#440154"];
  const DIVERGENTE = ["#b2182b", "#ef8a62", "#fddbc7", "#ededed", "#d1e5f0", "#67a9cf", "#2166ac"];
  // Indice del primo gradino su cui serve testo bianco.
  const PRIMO_SCURO = 3;

  function classi(valori, divergente) {
    const numeri = valori.filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
    if (!numeri.length) return { limiti: [], colori: [] };
    if (divergente) {
      const m = Math.max(...numeri.map(Math.abs)) || 1;
      const passo = m / 3.5;
      return { limiti: [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((k) => k * passo), colori: DIVERGENTE };
    }
    const min = Math.min(...numeri);
    const max = Math.max(...numeri);
    const n = SEQUENZIALE.length;
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
      const da = i === 0 ? null : scala.limiti[i - 1];
      const a = i < scala.limiti.length ? scala.limiti[i] : null;
      const testo =
        da === null ? `meno di ${formato(a)}` : a === null ? `da ${formato(da)}` : `${formato(da)} – ${formato(a)}`;
      return { colore, testo };
    });
  }

  window.Scala = { SEQUENZIALE, DIVERGENTE, PRIMO_SCURO, classi, coloreDi, legenda };
})();
