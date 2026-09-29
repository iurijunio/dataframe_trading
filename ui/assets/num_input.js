/* Rolar a página com o mouse sobre um <input type=number> focado muda o
 * valor dele (comportamento nativo do Chrome) em vez de rolar a página -
 * achado real: rolar a tela do Portfólio para ver as métricas, com o
 * campo de capital focado, trocou o capital de R$ 200.000 para R$ 10.000
 * sem nenhum clique (28/09/2026). preventDefault barra a MUDANÇA nativa
 * do valor logo no primeiro tick (blur sozinho só evita os próximos, o
 * primeiro tick já tinha aplicado a mudança antes do blur completar), e a
 * rolagem da página continua funcionando normal (o preventDefault é só
 * no wheel do input, não no scroll da página). */
(function () {
  document.addEventListener("wheel", function (e) {
    var alvo = e.target;
    if (alvo && alvo.tagName === "INPUT" && alvo.type === "number"
        && document.activeElement === alvo) {
      e.preventDefault();
      alvo.blur();
    }
  }, { passive: false });
})();
