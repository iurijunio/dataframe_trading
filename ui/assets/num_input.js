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

/* Casas decimais de um campo de número são as do step dele. Sem isto o
 * spinner do Chrome somava 0,1 em ponto flutuante e o valor virava
 * 2,3000000000000003, e a digitação livre mandava 2,123456 para o plano e
 * para o motor (multiplicador do alvo, 06/10/2026). Arredonda no
 * change/blur/Enter na fase de captura, ANTES do Dash ler o valor — o
 * redondinho do passo é a régua do campo: corretagem de passo 0,01 mantém
 * 0,35, multiplicador de passo 0,1 vira 2,1, campo inteiro vira 4. Nunca
 * cola no múltiplo do step (capital com passo 1000 aceita 10500), só
 * limita casa decimal. */
(function () {
  function casas(step) {
    if (!step || step === "any") return null;
    var p = String(step).split(".")[1];
    return p ? p.length : 0;
  }
  function arredondar(alvo) {
    if (!alvo || alvo.tagName !== "INPUT" || alvo.type !== "number") return;
    var n = casas(alvo.step);
    if (n === null || alvo.value === "") return;
    var v = parseFloat(alvo.value);
    if (isNaN(v)) return;
    var f = Math.pow(10, n);
    var limpo = String(Math.round(v * f) / f);
    if (alvo.value !== limpo) alvo.value = limpo;
  }
  document.addEventListener("change", function (e) { arredondar(e.target); }, true);
  document.addEventListener("blur", function (e) { arredondar(e.target); }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Enter") arredondar(e.target);
  }, true);
})();
