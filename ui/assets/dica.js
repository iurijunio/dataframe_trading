/* Balão do (?) preso ao <body>, e não ao cartão.
 *
 * Em CSS puro o tooltip é um ::after posicionado dentro do cartão — e não
 * existe jeito de fazê-lo escapar do recorte de um ancestral com
 * `overflow`. Dentro da aba, que rola, o balão dos cartões da primeira
 * linha era cortado por cima e o dos cartões das laterais por fora.
 *
 * Um único nó em `position: fixed`, posicionado a cada hover, resolve os
 * dois casos: nada o recorta, e dá para virá-lo para baixo quando não cabe
 * acima e grudá-lo na borda quando não cabe de lado.
 *
 * Delegação no documento porque o Dash troca os cartões a cada backtest:
 * ouvinte por elemento morreria junto com o cartão. */
(function () {
  var MARGEM = 10;
  var balao = null;

  function no() {
    if (!balao) {
      balao = document.createElement("div");
      balao.className = "dica-balao";
      document.body.appendChild(balao);
    }
    return balao;
  }

  function mostrar(alvo) {
    var texto = alvo.getAttribute("data-dica");
    if (!texto) return;
    var b = no();
    b.textContent = texto;
    // mede antes de mostrar: sem largura resolvida nao da para centralizar
    b.style.visibility = "hidden";
    b.style.opacity = "0";
    b.style.left = "0px";
    b.style.top = "0px";
    b.classList.add("on");

    var r = alvo.getBoundingClientRect();
    var cx = b.offsetWidth;
    var cy = b.offsetHeight;

    var x = r.left + r.width / 2 - cx / 2;
    x = Math.max(MARGEM, Math.min(x, window.innerWidth - cx - MARGEM));

    var y = r.top - cy - 9;                 // acima por padrao
    if (y < MARGEM) y = r.bottom + 9;       // nao coube: vai para baixo

    b.style.left = Math.round(x) + "px";
    b.style.top = Math.round(y) + "px";
    b.style.visibility = "visible";
    b.style.opacity = "1";
  }

  function esconder() {
    if (!balao) return;
    balao.style.opacity = "0";
    balao.style.visibility = "hidden";
    balao.classList.remove("on");
  }

  function marca(alvo) {
    return alvo && alvo.closest ? alvo.closest(".dica-mark") : null;
  }

  document.addEventListener("mouseover", function (e) {
    var m = marca(e.target);
    if (m) mostrar(m);
  });
  document.addEventListener("mouseout", function (e) {
    if (marca(e.target)) esconder();
  });
  // pelo teclado: Tab chega no (?) e o balão abre; sair do foco fecha.
  // O foco ROLA a página até o elemento, e a rolagem fecha o balão: abrir na
  // hora fazia ele abrir e fechar no mesmo instante. Abre depois da rolagem.
  var abertoPeloFoco = 0;
  document.addEventListener("focusin", function (e) {
    var m = marca(e.target);
    if (!m) return;
    setTimeout(function () {
      if (document.activeElement === m) {
        abertoPeloFoco = Date.now();
        mostrar(m);
      }
    }, 60);
  });
  document.addEventListener("focusout", function (e) {
    if (marca(e.target)) esconder();
  });
  // com o balao aberto, rolar a aba o deixava parado sobre o lugar antigo
  window.addEventListener("scroll", function () {
    // a rolagem que o próprio foco provocou não fecha o balão que ele abriu
    if (Date.now() - abertoPeloFoco > 250) esconder();
  }, true);
  window.addEventListener("resize", esconder);
})();
