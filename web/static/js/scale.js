// Scale di colore e legende condivise dai moduli con coropletica.
// Rampa sequenziale blu (chiaro = poco, scuro = tanto) e scala divergente
// rosso-grigio-blu per le variazioni, dalla palette di riferimento.
(() => {
  const SEQUENZIALE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
  const DIVERGENTE = ["#a82c2b", "#e34948", "#f3a9a8", "#f0efec", "#9ec5f4", "#3987e5", "#184f95"];

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

  window.Scala = { SEQUENZIALE, DIVERGENTE, classi, coloreDi, legenda };
})();
