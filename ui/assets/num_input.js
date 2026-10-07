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

/* O spinner do Chrome soma o passo em ponto flutuante e o valor vira
 * 2,3000000000000003 (multiplicador do alvo, 06/10/2026). Limpa só esse
 * resto de conta (10 casas), nunca o que foi digitado: a versão anterior
 * cortava nas casas do step e mudava o dado em silêncio — limite de perda
 * R$ 37,50 com passo 50 virava 38, passo de faixa 0,25 virava 0,3 e 0,04
 * virava 0 (o campo marcado deixava de ser minerado). Roda no
 * change/blur/Enter na fase de captura, ANTES do Dash ler o valor, e troca
 * o valor pelo setter nativo + evento `input`: atribuir `value` direto
 * passa despercebido pelo React, e o Dash ficaria com o número antigo
 * enquanto a tela mostra o novo. */
(function () {
  var setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, "value").set;
  function arredondar(alvo) {
    if (!alvo || alvo.tagName !== "INPUT" || alvo.type !== "number") return;
    if (alvo.value === "") return;
    var v = parseFloat(alvo.value);
    if (isNaN(v)) return;
    var limpo = String(Math.round(v * 1e10) / 1e10);
    if (alvo.value !== limpo) {
      setter.call(alvo, limpo);
      alvo.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  document.addEventListener("change", function (e) { arredondar(e.target); }, true);
  document.addEventListener("blur", function (e) { arredondar(e.target); }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter") arredondar(e.target);
  }, true);
})();
