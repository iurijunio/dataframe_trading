/* Alarme da parte 4: chamado aberto ou conta travada. O usuário pode estar
 * em outra aba do app ou em outra janela; o título da aba piscando e um
 * bipe curto o trazem de volta. Só toca uma vez por chamado NOVO — a lista
 * de chaves vem em data-chaves. */
(function () {
  var original = document.title, timer = null, vistos = {};
  function bipe() {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.35, 0.7].forEach(function (t) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
        g.gain.setValueAtTime(0.15, ctx.currentTime + t);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.2);
      });
      // cada bipe abre um contexto de áudio; o navegador limita quantos
      // ficam abertos, então fecha depois dos 3 bipes (~0,9 s)
      setTimeout(function () { ctx.close(); }, 1500);
    } catch (e) { /* navegador sem áudio: fica o título */ }
  }
  function aplicar(el) {
    var ligado = el.getAttribute("data-alarme") === "1";
    var chaves = (el.getAttribute("data-chaves") || "").split("|").filter(Boolean);
    var novo = chaves.some(function (c) { return !vistos[c]; });
    chaves.forEach(function (c) { vistos[c] = true; });
    if (ligado && novo) bipe();
    if (ligado && !timer) {
      original = document.title;
      timer = setInterval(function () {
        document.title = document.title === original ? "⚠ Precisa de você" : original;
      }, 1000);
    } else if (!ligado && timer) {
      clearInterval(timer); timer = null; document.title = original;
    }
  }
  new MutationObserver(function () {
    var el = document.getElementById("ord-alarme");
    if (el) aplicar(el);
  }).observe(document.documentElement, { subtree: true, attributes: true,
                                         attributeFilter: ["data-alarme", "data-chaves"] });
})();
