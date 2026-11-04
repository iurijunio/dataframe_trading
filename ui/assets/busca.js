/* Mineração › Busca automática — a tela do layout B (protótipo aprovado em
 * 03/11/2026, docs/superpowers/specs/2026-11-03-busca-automatica/layout-b.html).
 *
 * O comportamento é o do protótipo (mapa com teclado e tooltip, pulso da casa
 * nova, lista ordenável, gaveta com foco preso, confirmação de exclusão),
 * trocando os dados simulados pelos do servidor:
 *   window.buscaTela.dados(d)    <- store busca-dados (ui/callbacks_busca.py)
 *   window.buscaTela.detalhe(d)  <- store busca-detalhe
 * e os cliques viram stores que o servidor atende:
 *   busca-acao (controles), busca-pedido (detalhe), busca-ir (Backtest/Varredura).
 * Desenho mexe aqui E no protótipo juntos: ele é o contrato. */
(function () {
  'use strict';

  var D = null, root = null;
  var view = 'mapa', axis = 'horario', metric = 'fr';
  var sortK = 'fr', sortDir = -1, onlyGood = false, showAll = false;
  var di = null, drOpen = false, lastFocus = null, detCache = {}, pedidos = {}, pedidoN = 0;
  var rasc = null, rascDe = undefined, cpuTouched = false, ctlLocal = null;
  var aceso = {}, acesoChave = '', litTick = {}, tickN = 0, cfOpener = null, delId = null;
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* ------------------------------------------------------------ util */
  function $(id) { return root.querySelector('#' + id); }
  function $$(sel, el) { return Array.prototype.slice.call((el || root).querySelectorAll(sel)); }
  function fmt(n) { return Math.round(n).toLocaleString('pt-BR'); }
  function dec(n, d) { return Number(n).toLocaleString('pt-BR', {minimumFractionDigits: d, maximumFractionDigits: d}); }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  function enviar(id, dados) {
    if (window.dash_clientside && window.dash_clientside.set_props)
      window.dash_clientside.set_props(id, {data: Object.assign({n: Date.now()}, dados)});
  }
  function acao(nome, extra) { enviar('busca-acao', Object.assign({acao: nome, id: D && D.busca_id}, extra || {})); }
  function hx(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function mix(c1, c2, a) { return [0, 1, 2].map(function (k) { return Math.round(c2[k] + (c1[k] - c2[k]) * a); }); }
  function lum(c) { var a = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; }
  function ink(c) { var L = lum(c); return (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? '#fff' : '#000'; }
  function css(c) { return 'rgb(' + c.join(',') + ')'; }
  function ramp(stops, v) {
    if (v == null) v = Infinity;
    if (v <= stops[0][0]) return hx(stops[0][1]);
    for (var i = 1; i < stops.length; i++) {
      if (v <= stops[i][0]) {
        var a = hx(stops[i - 1][1]), b = hx(stops[i][1]), t = (v - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]);
        return [0, 1, 2].map(function (k) { return Math.round(a[k] + (b[k] - a[k]) * t); });
      }
    }
    return hx(stops[stops.length - 1][1]);
  }
  function setTip(el, tip) { el.setAttribute('data-tip', tip); el.setAttribute('aria-label', (el.getAttribute('data-h') || 'Ajuda') + ': ' + tip); }
  function initTips(scope) { $$('.b-q', scope).forEach(function (q) { setTip(q, q.getAttribute('data-tip') || ''); }); }
  function q(h, tip, cls) { return '<button type="button" class="b-q' + (cls ? ' ' + cls : '') + '" data-h="' + esc(h) + '" data-tip="' + esc(tip) + '">?</button>'; }
  var LOCK = '<svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/><path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';
  var PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5l9 5.5-9 5.5z" fill="currentColor"/></svg>';
  var TRASH = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4h11M6 4V2.6h4V4M4 4l.7 9.4h6.6L12 4M6.6 6.6v4.6M9.4 6.6v4.6"/></svg>';

  /* ------------------------------------------------------------ esqueleto */
  function esqueleto() {
    return '' +
'<section class="b-main" aria-label="Busca automática">' +
'  <section class="b-strip" aria-label="Andamento da busca">' +
'    <div><div class="l">Testes</div><div class="v"><span id="b-k-t">—</span><small id="b-k-tde"></small></div>' +
'      <div class="b-bar" id="b-k-bar" role="progressbar" aria-label="Progresso da busca" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="b-k-barf" style="width:0%"></i></div></div>' +
'    <div><div class="l">Nichos' + q('Ajuda sobre nichos', '', '') .replace('data-tip=""', 'id="b-q-nichos" data-tip=""') + '</div><div class="v"><span id="b-k-n">—</span><small id="b-k-nde"></small></div></div>' +
'    <div><div class="l">Bons' + q('Ajuda sobre nichos bons', '').replace('data-tip=""', 'id="b-q-bons" data-tip=""') + '</div><div class="v pos" id="b-k-b">—</div></div>' +
'    <div><div class="l"><span id="b-k-bl">Melhor FR</span>' + q('Ajuda sobre o melhor', '').replace('data-tip=""', 'id="b-q-melhor" data-tip=""') + '</div>' +
'      <button type="button" class="b-kbest" id="b-k-best"><span id="b-k-fr">—</span><span class="st" aria-hidden="true">★</span></button></div>' +
'    <div><div class="l"><span id="b-k-tl">Decorrido</span>' + q('Ajuda sobre o tempo', 'A linha mostra quantos nichos estavam acesos ao longo da busca. Se achatou, a busca parou de achar regiões novas.', 'r') + '</div>' +
'      <div class="v" style="font-size:16px"><span id="b-k-dec">—</span><small id="b-k-fal"></small></div>' +
'      <svg class="b-spark" id="b-k-spark" viewBox="0 0 200 22" preserveAspectRatio="none" role="img" aria-label="Nichos acesos ao longo do tempo"><polyline id="b-k-sparkl" fill="none" stroke="#22E4FF" stroke-width="1.6" vector-effect="non-scaling-stroke" points=""/></svg></div>' +
'  </section>' +
'  <div class="b-vh">' +
'    <div class="b-tabs" role="tablist" aria-label="Visão">' +
'      <button type="button" role="tab" id="b-v-mapa" aria-selected="true" aria-controls="b-p-mapa" tabindex="0">Mapa</button>' +
'      <button type="button" role="tab" id="b-v-lista" aria-selected="false" aria-controls="b-p-lista" tabindex="-1">Lista</button>' +
'      <button type="button" role="tab" id="b-v-esp" aria-selected="false" aria-controls="b-p-esp" tabindex="-1">Espaço de busca<svg id="b-esp-lock" viewBox="0 0 16 16" width="11" height="11" role="img" aria-label="travado"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/><path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg></button>' +
'    </div>' +
'    <span class="b-pill green sm" id="b-live"><span class="b-dot" aria-hidden="true"></span>ao vivo</span>' +
'  </div>' +
'  <section id="b-p-mapa" role="tabpanel" aria-labelledby="b-v-mapa" tabindex="-1"><div class="b-mapcard">' +
'    <div class="b-maphead" id="b-mapctl">' +
'      <fieldset class="b-seg" id="b-axis"><legend>Colunas do mapa</legend><span class="seglbl" aria-hidden="true">Colunas</span>' +
'        <label><input type="radio" name="b-axis" value="horario" checked>Horário</label><label><input type="radio" name="b-axis" value="dias">Dias</label><label><input type="radio" name="b-axis" value="direcao">Direção</label></fieldset>' +
'      <span style="display:inline-flex;align-items:center;gap:8px"><label class="lbl" for="b-mt">Cor</label>' +
'        <select id="b-mt" class="b-dd" style="width:200px"><option value="fr">Fator de recuperação</option><option value="pf">Profit factor</option><option value="trades">Trades</option></select></span>' +
'      <span class="b-mapcount" id="b-mapcount"></span>' +
         q('Ajuda sobre o mapa', 'Linhas: tempo gráfico. Colunas: o que você escolher. Cada casa mostra o melhor resultado guardado naquele nicho. Trocar colunas ou cor não mexe na busca. Setas do teclado andam pelo mapa; Enter abre.', 'r') +
'    </div>' +
'    <div class="b-empty" id="b-map-empty" hidden><b>Nenhum nicho ainda</b><button type="button" class="b-btn main" data-go="ini">' + PLAY + 'Iniciar busca</button></div>' +
'    <div id="b-map-has"><div class="b-mapwrap"><table class="b-map" id="b-map" role="grid" aria-label="Mapa de nichos"></table></div>' +
'      <div class="b-mapfoot"><div class="b-leg"><span class="nm" id="b-leg-nm"></span><div class="b-legbar"><i id="b-leg-grad" aria-hidden="true"></i><div class="b-ticks" id="b-leg-ticks"></div></div></div>' +
'        <div class="b-sws"><span><span class="b-sw low" aria-hidden="true"></span><span id="b-sw-min">menos de 400 trades</span></span><span><span class="b-sw un" aria-hidden="true"></span>não testado</span><span><span class="b-sw best" aria-hidden="true"></span>melhor</span></div></div></div>' +
'  </div></section>' +
'  <section id="b-p-lista" role="tabpanel" aria-labelledby="b-v-lista" tabindex="-1" hidden>' +
'    <div class="b-empty" id="b-l-empty" hidden><b>Nenhum nicho ainda</b><button type="button" class="b-btn main" data-go="ini">' + PLAY + 'Iniciar busca</button></div>' +
'    <div id="b-l-has"><div class="b-lbar"><button type="button" class="b-chip" id="b-l-good" aria-pressed="false">Só bons</button><span class="b-dim" id="b-l-count" style="font-size:11.5px"></span></div>' +
'      <table class="b-list" id="b-list"><caption class="b-sr">Nichos com resultado</caption>' +
'        <colgroup><col style="width:30px"><col style="width:150px"><col><col style="width:132px"><col style="width:62px"><col style="width:112px"><col style="width:86px"><col style="width:100px"></colgroup>' +
'        <thead><tr><th scope="col" class="rk"><span aria-hidden="true">#</span><span class="b-sr">Posição</span></th>' +
'          <th scope="col" data-k="nicho" aria-sort="none"><button type="button" class="b-sort" data-k="nicho">Nicho<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9 1 4h8z" fill="currentColor"/></svg></button></th>' +
'          <th scope="col">Selos</th>' +
'          <th scope="col" class="num" data-k="fr" aria-sort="descending"><button type="button" class="b-sort" data-k="fr">FR<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9 1 4h8z" fill="currentColor"/></svg></button>' + q('Ajuda sobre FR', 'Fator de recuperação do melhor do nicho. Embaixo, a mediana dos membros: perto do melhor indica região sólida. Bom acima de 3; fraco abaixo de 1,5.', 'r') + '</th>' +
'          <th scope="col" class="num" data-k="pf" aria-sort="none"><button type="button" class="b-sort" data-k="pf">PF<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9 1 4h8z" fill="currentColor"/></svg></button></th>' +
'          <th scope="col" class="num" data-k="trades" aria-sort="none"><button type="button" class="b-sort" data-k="trades">Trades<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9 1 4h8z" fill="currentColor"/></svg></button></th>' +
'          <th scope="col" class="num" data-k="membros" aria-sort="none"><button type="button" class="b-sort" data-k="membros">Membros<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9 1 4h8z" fill="currentColor"/></svg></button>' + q('Ajuda sobre membros', 'Combinações parecidas que também passaram. Menos de 15 pode ser pico isolado.', 'r') + '</th>' +
'          <th scope="col">Evolução' + q('Ajuda sobre evolução', 'Como o melhor do nicho subiu ao longo da busca. Linha que ainda sobe no fim: o nicho pode melhorar mais.', 'r') + '</th></tr></thead>' +
'        <tbody id="b-lbody"></tbody></table>' +
'      <div class="b-more" id="b-l-more"><span id="b-l-rest"></span><button type="button" class="b-btn ghost sm" id="b-l-all">Mostrar todos</button></div></div>' +
'  </section>' +
'  <section id="b-p-esp" role="tabpanel" aria-labelledby="b-v-esp" tabindex="-1" hidden>' +
'    <div class="b-cfghead" id="b-cfg-lock"><span class="b-pill gray sm">' + LOCK + 'só leitura</span>' + q('Ajuda sobre o espaço travado', 'O espaço de busca fica travado enquanto a busca existe. Para mudar faixas ou passos, use Nova busca.') + '</div>' +
'    <fieldset class="b-cfg" id="b-cfg"><legend class="b-sr">Espaço de busca</legend><div id="b-cfg-corpo"></div></fieldset>' +
'  </section>' +
'</section>' +
'<aside class="b-rail" aria-label="Controle da busca">' +
'  <div class="b-rsec"><div class="b-state"><span id="b-st-pill" class="b-pill lg gray"><span class="b-spin" id="b-st-spin" aria-hidden="true" hidden></span><span id="b-st-txt">Parada</span></span>' +
       q('Ajuda sobre o estado da busca', '', 'r').replace('class="b-q r"', 'class="b-q r" id="b-st-q"') + '<span class="when" id="b-st-when"></span></div>' +
'    <div class="b-sr" role="status" aria-live="polite" id="b-st-live"></div></div>' +
'  <div class="b-rsec b-acts">' +
'    <button type="button" class="b-btn main full" id="b-ini">' + PLAY + 'Iniciar busca</button>' +
'    <button type="button" class="b-btn warn" id="b-pau"><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3" width="3" height="10" fill="currentColor"/><rect x="9.5" y="3" width="3" height="10" fill="currentColor"/></svg>Pausar</button>' +
'    <button type="button" class="b-btn main" id="b-con">' + PLAY + 'Continuar</button>' +
'    <button type="button" class="b-btn neg full" id="b-par"><svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3.5" width="9" height="9" rx="1" fill="currentColor"/></svg>Parar e guardar</button>' +
'    <button type="button" class="b-btn ghost sm full" id="b-nova"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" fill="none"/></svg>Nova busca</button></div>' +
'  <div class="b-rsec"><h3>Parada</h3>' +
'    <div class="b-rrow"><span class="b-chk"><input type="checkbox" id="b-c-hora"><label for="b-c-hora">Parar às</label></span>' +
'      <input type="time" class="b-inp" id="b-i-hora" value="08:30" aria-label="Horário para parar">' + q('Ajuda sobre parar às', 'Para sozinha neste horário e guarda tudo. Desligado: roda até você parar ou até o limite. Dá para mudar com a busca rodando.', 'r') + '</div>' +
'    <div class="b-rrow"><span class="b-chk"><input type="checkbox" id="b-c-lim"><label for="b-c-lim">Limite de testes</label></span>' +
'      <input class="b-inp" id="b-i-lim" value="—" disabled inputmode="numeric" aria-label="Número máximo de testes">' + q('Ajuda sobre limite de testes', 'Para depois deste número de testes. Vale o que vier primeiro: horário ou limite.', 'r') + '</div></div>' +
'  <div class="b-rsec"><h3><label for="b-n-cpu">Núcleos</label>' + q('Ajuda sobre núcleos', '', 'r').replace('class="b-q r"', 'class="b-q r" id="b-q-cpu"') +
'      <span class="b-pill blue sm" id="b-cpu-ap" style="margin-left:auto" hidden>aplicando</span></h3>' +
'    <div style="display:flex;align-items:center;gap:8px"><span class="b-stepper"><button type="button" id="b-cpu-m" aria-label="Menos um núcleo">−</button><input id="b-n-cpu" type="text" inputmode="numeric" value="20"><button type="button" id="b-cpu-p" aria-label="Mais um núcleo">+</button></span>' +
'      <span class="b-dim" id="b-cpu-de">de 24</span><button type="button" class="b-btn ghost sm" id="b-cpu-def" style="margin-left:auto" hidden>Padrão</button></div>' +
'    <div class="b-cpubar" id="b-cpubar" aria-hidden="true"></div></div>' +
'  <div class="b-rsec"><h3 id="b-sv-h">Buscas salvas</h3><ul class="b-saved" id="b-saved" aria-labelledby="b-sv-h"></ul><div class="b-svmsg" id="b-svmsg" role="status" aria-live="polite"></div></div>' +
'</aside>' +
'<div class="b-scrim" id="b-scrim" hidden></div>' +
'<div class="b-drawer" id="b-drawer" role="dialog" aria-modal="true" aria-labelledby="b-dr-ttl" hidden>' +
'  <div class="b-dr-head"><div class="b-dr-row"><h2 class="b-dr-ttl" id="b-dr-ttl" tabindex="-1"><span id="b-dr-tf"></span><span id="b-dr-cv"></span></h2>' +
'    <div class="b-dr-nav"><button type="button" class="b-ico" id="b-dr-prev" data-tip=""><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3 5 8l5 5"/></svg></button>' +
'      <span class="pos" id="b-dr-pos"></span><button type="button" class="b-ico" id="b-dr-next" data-tip=""><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3l5 5-5 5"/></svg></button>' +
'      <span class="sep" aria-hidden="true"></span><button type="button" class="b-ico" id="b-dr-close" aria-label="Fechar o nicho" data-tip="Fechar (Esc)"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg></button></div></div>' +
'    <div class="b-dr-pills" id="b-dr-pills"></div></div>' +
'  <div class="b-dr-body" id="b-dr-body" tabindex="0" aria-label="Detalhe do nicho"></div>' +
'  <div class="b-dr-foot">' + q('Ajuda sobre as ações do nicho', 'Minerar a região leva para a Varredura com tempo gráfico, horário, dias, stop, alvo e as faixas dos membros já preenchidos. Abrir o campeão leva a melhor combinação do nicho para o Backtest.', 'r up').replace('class="b-q r up"', 'class="b-q r up" style="margin-right:auto"') +
'    <button type="button" class="b-btn ghost" id="b-dr-bt">Abrir o campeão no Backtest</button><button type="button" class="b-btn main" id="b-dr-min">Minerar a região</button></div>' +
'  <div class="b-sr" role="status" aria-live="polite" id="b-dr-live"></div></div>' +
'<div class="b-cf" id="b-cf" role="alertdialog" aria-modal="true" aria-labelledby="b-cf-t" aria-describedby="b-cf-d" hidden>' +
'  <h2 id="b-cf-t" tabindex="-1">Excluir a busca?</h2><p id="b-cf-d"></p>' +
'  <div class="acts"><button type="button" class="b-btn ghost" id="b-cf-no">Manter busca</button><button type="button" class="b-btn negfill" id="b-cf-yes">Excluir busca</button></div></div>' +
'<div class="b-tip" id="b-tip" aria-hidden="true" hidden></div>';
  }

  /* ------------------------------------------------------------ estados */
  var S = {
    parada: {pill: 'gray', txt: 'Parada', spin: 0, b: {ini: 1, pau: 0, con: 0, par: 0, nova: 0}, lock: 0, live: 0, barc: ''},
    rodando: {pill: 'green', txt: 'Rodando', spin: 1, b: {ini: 0, pau: 1, con: 0, par: 1, nova: 0}, lock: 1, live: 1, barc: ''},
    pausada: {pill: 'amber', txt: 'Pausada', spin: 0, b: {ini: 0, pau: 0, con: 1, par: 1, nova: 0}, lock: 1, live: 0, barc: 'amber'},
    concluida: {pill: 'blue', txt: 'Concluída', spin: 0, b: {ini: 0, pau: 0, con: 1, par: 0, nova: 1}, lock: 1, live: 0, barc: 'blue'},
    interrompida: {pill: 'rose', txt: 'Interrompida', spin: 0, b: {ini: 0, pau: 0, con: 1, par: 0, nova: 1}, lock: 1, live: 0, barc: 'rose'}
  };
  var STPILL = {parada: ['gray', 'parada'], rodando: ['green', 'rodando'], pausada: ['amber', 'pausada'], concluida: ['blue', 'concluída'], interrompida: ['rose', 'interrompida']};
  function st() { return S[(D && D.status) || 'parada'] || S.parada; }
  function status() { return (D && D.status) || 'parada'; }

  /* ------------------------------------------------------------ mapa */
  function mapa() { return D && D.mapas ? D.mapas[axis] : null; }
  function casas() { var m = mapa(); return m ? m.casas : []; }
  function nc() { var m = mapa(); return m ? m.colunas.length : 1; }
  function abre(x) { return !!x && x.estado === 'ok'; }
  function val(x) { return metric === 'fr' ? x.fr : (metric === 'pf' ? x.pf : x.trades); }
  function txt(x) {
    var v = val(x);
    if (v == null) return '∞';
    return metric === 'trades' ? fmt(v) : dec(v, metric === 'fr' ? 1 : 2);
  }
  function frTxt(x) { return x.fr == null ? '∞' : dec(x.fr, 1); }
  function nome(x) { var m = mapa(); return m.linhas[x.linha] + ', ' + m.colunas[x.coluna]; }
  function minimo() { return (D && D.minimo) || 400; }

  function renderMap() {
    var m = mapa(), map = $('b-map');
    if (!m) { map.innerHTML = ''; return; }
    var h = '<thead><tr><th scope="col" class="b-corner" rowspan="2">Tempo</th><th scope="colgroup" class="b-axcap" colspan="' + m.colunas.length + '">' + esc(m.nome_eixo) + '</th></tr><tr class="cols">';
    m.colunas.forEach(function (c) { h += '<th scope="col">' + esc(c) + '</th>'; });
    h += '</tr></thead><tbody>';
    m.linhas.forEach(function (tf, r) {
      h += '<tr><th scope="row">' + esc(tf) + '</th>';
      m.colunas.forEach(function (c, ci) { h += '<td role="gridcell"><button type="button" class="b-cell" data-i="' + (r * m.colunas.length + ci) + '" tabindex="-1"></button></td>'; });
      h += '</tr>';
    });
    map.innerHTML = h + '</tbody>';
    $$('.b-cell', map).forEach(function (b) { b.addEventListener('animationend', function () { b.classList.remove('new'); }); });
    renderLegend();
    paint();
  }
  function renderLegend() {
    var sc = D.legendas[metric], st0 = sc.paradas, a = st0[0][0], z = st0[st0.length - 1][0];
    $('b-leg-nm').textContent = sc.nome;
    $('b-leg-grad').style.background = 'linear-gradient(90deg,' + st0.map(function (s) { return s[1] + ' ' + ((s[0] - a) / (z - a) * 100).toFixed(1) + '%'; }).join(',') + ')';
    $('b-leg-ticks').innerHTML = st0.map(function (s, i) {
      var lab = metric === 'trades' ? fmt(s[0]) : dec(s[0], metric === 'fr' ? (s[0] % 1 ? 1 : 0) : 2);
      if (i === st0.length - 1) lab += '+';
      return '<span style="left:' + ((s[0] - a) / (z - a) * 100).toFixed(1) + '%">' + lab + '</span>';
    }).join('');
  }
  function paint() {
    var m = mapa(), map = $('b-map'), any = false, sc = D.legendas[metric];
    var chave = D.busca_id + '|' + axis, novo = {};
    if (chave !== acesoChave) { aceso = {}; acesoChave = chave; var primeira = true; }
    tickN++;
    $$('.b-cell', map).forEach(function (b) {
      var x = m.casas[+b.dataset.i], cls = 'b-cell';
      b.style.background = ''; b.style.color = '';
      if (x.estado === 'vazia') { cls += ' un'; b.textContent = ''; b.setAttribute('aria-label', nome(x) + ': ainda não testado'); b.setAttribute('aria-disabled', 'true'); }
      else if (x.estado === 'poucos') { cls += ' low'; b.textContent = fmt(x.trades || 0); b.setAttribute('aria-label', nome(x) + ': só ' + fmt(x.trades || 0) + ' trades, menos de ' + fmt(minimo())); b.setAttribute('aria-disabled', 'true'); }
      else {
        var c = ramp(sc.paradas, val(x)); b.style.background = css(c); b.style.color = ink(c);
        b.textContent = txt(x); b.removeAttribute('aria-disabled');
        b.setAttribute('aria-label', nome(x) + ': FR ' + frTxt(x) + ', PF ' + (x.pf == null ? '∞' : dec(x.pf, 2)) + ', ' + fmt(x.trades) + ' trades' + (x.membros != null ? ', ' + x.membros + ' membros' : '') + (x.melhor ? ', melhor do mapa' : ''));
        if (x.melhor) cls += ' best';
        var k = x.linha + ':' + x.coluna; novo[k] = 1;
        if (!primeira && !aceso[k] && status() === 'rodando') { litTick[chave + k] = tickN; if (!reduce) cls += ' new'; }
      }
      if (b.tabIndex === 0) any = true;
      b.className = cls;
    });
    aceso = novo;
    if (!any) { var bi = m.casas.findIndex(function (x) { return x.melhor; }); var f = map.querySelector('[data-i="' + (bi >= 0 ? bi : 0) + '"]'); if (f) f.tabIndex = 0; }
    $('b-mapcount').textContent = m.n_com_resultado + ' de ' + m.n_casas + ' com resultado';
  }
  function focusCell(j) {
    var t = $('b-map').querySelector('[data-i="' + j + '"]'); if (!t) return;
    $$('.b-cell', $('b-map')).forEach(function (z) { z.tabIndex = -1; }); t.tabIndex = 0; t.focus();
  }
  function dims(x) { return x.dims || []; }
  function tipHTML(x) {
    var m = mapa(), h = '<div class="t-h"><b>' + esc(m.linhas[x.linha]) + '</b><span>' + esc(m.colunas[x.coluna]) + '</span></div>';
    if (x.estado === 'vazia') return h + '<p class="b-dim">Ainda não testado</p>';
    if (x.estado === 'poucos') return h + '<p class="b-warn">Só ' + fmt(x.trades || 0) + ' trades, menos de ' + fmt(minimo()) + '</p>';
    h += '<dl>';
    dims(x).forEach(function (d) { h += '<dt>' + esc(d[0]) + '</dt><dd>' + esc(d[1]) + '</dd>'; });
    h += '<hr><dt>FR</dt><dd class="big">' + frTxt(x) + '</dd><dt>PF</dt><dd>' + (x.pf == null ? '∞' : dec(x.pf, 2)) + '</dd><dt>Trades</dt><dd>' + fmt(x.trades) + '</dd>';
    if (x.membros != null) h += '<dt>Membros</dt><dd' + (x.membros < 15 ? ' class="b-warn"' : '') + '>' + x.membros + '</dd>';
    h += '</dl>';
    if (x.melhor) h += '<p class="b-cy">★ Melhor do mapa</p>';
    return h + '<p class="t-f">Clique ou Enter para abrir</p>';
  }
  function showTip(b) {
    var tip = $('b-tip'), x = casas()[+b.dataset.i]; if (!x) return;
    tip._cell = b; tip.innerHTML = tipHTML(x); tip.hidden = false;
    var r = b.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    var top = r.bottom + 8; if (top + h > window.innerHeight - 8) top = r.top - h - 8;
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function hideTip() { var t = $('b-tip'); if (t) { t.hidden = true; t._cell = null; } }

  /* ------------------------------------------------------------ lista */
  // selos pela META da busca (o contador "Bons" usa o mesmo corte); lucro e
  // drawdown não têm corte de "bom"
  function crit() { return (D && D.criterio) || 'fr'; }
  function bom(x) { var c = crit(); if (c === 'fr') return x.fr == null || x.fr >= 3; if (c === 'pf') return x.pf == null || x.pf >= 1.25; return false; }
  function fraco(x) { var c = crit(); if (c === 'fr') return x.fr != null && x.fr < 1.5; if (c === 'pf') return x.pf != null && x.pf < 1.1; return false; }
  function chaveOrd(x) {
    if (sortK === 'fr') return x.fr == null ? Infinity : x.fr;
    if (sortK === 'pf') return x.pf == null ? Infinity : x.pf;
    if (sortK === 'trades') return x.trades;
    if (sortK === 'membros') return x.membros || 0;
    return x.linha * 1000 + x.coluna;
  }
  function listRows() {
    var rows = [];
    casas().forEach(function (x, i) { if (abre(x) && (!onlyGood || bom(x))) rows.push(i); });
    rows.sort(function (a, b) { var A = chaveOrd(casas()[a]), B = chaveOrd(casas()[b]); return (A > B ? 1 : A < B ? -1 : 0) * sortDir; });
    return rows;
  }
  function sparkSVG(x) {
    var hs = x.evolucao || []; if (!hs.length) return '<span class="b-dim">—</span>';
    var mx = Math.max.apply(null, hs.concat([6])), passo = hs.length > 1 ? 80 / (hs.length - 1) : 0;
    var pts = hs.map(function (v, i) { return (2 + i * passo).toFixed(1) + ',' + (20 - Math.max(0, v) / mx * 18).toFixed(1); });
    var last = pts[pts.length - 1].split(',');
    return '<svg class="b-lspark" viewBox="0 0 84 22" role="img" aria-label="Melhor subiu de ' + dec(hs[0], 1) + ' para ' + dec(hs[hs.length - 1], 1) + '"><polyline fill="none" stroke="#22E4FF" stroke-width="1.4" stroke-linejoin="round" points="' + pts.join(' ') + '"/><circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.2" fill="#22E4FF"/></svg>';
  }
  function seals(x) {
    var s = '';
    if (x.melhor) s += '<span class="b-pill cy sm">★ melhor</span>';
    if (bom(x)) s += '<span class="b-pill green sm">bom</span>'; else if (fraco(x)) s += '<span class="b-pill rose sm">fraco</span>';
    if (x.membros != null && x.membros < 15) s += '<span class="b-pill amber sm">poucos membros</span>';
    var k = acesoChave + x.linha + ':' + x.coluna;
    if (status() === 'rodando' && litTick[k] !== undefined && tickN - litTick[k] <= 5) s += '<span class="b-pill blue sm">novo</span>';
    return s || '<span class="b-dim">—</span>';
  }
  function renderList() {
    if (!mapa()) return;
    var all = listRows(), rows = showAll ? all : all.slice(0, 12), maxTr = 1;
    all.forEach(function (i) { maxTr = Math.max(maxTr, casas()[i].trades || 0); });
    var act = document.activeElement, foc = (act && act.classList && act.classList.contains('b-nbtn')) ? act.dataset.i : null;
    $('b-l-count').textContent = all.length + (all.length === 1 ? ' nicho' : ' nichos');
    $('b-l-more').hidden = all.length <= 12;
    $('b-l-rest').textContent = showAll ? '' : 'mais ' + (all.length - 12) + ' nichos';
    $('b-l-all').textContent = showAll ? 'Mostrar só os 12 primeiros' : 'Mostrar todos (' + all.length + ')';
    $$('.b-list th[data-k]').forEach(function (th) { th.setAttribute('aria-sort', th.dataset.k === sortK ? (sortDir < 0 ? 'descending' : 'ascending') : 'none'); });
    var h = '';
    if (!rows.length) h = '<tr><td colspan="8" class="b-dim" style="text-align:center;padding:24px">' + (onlyGood ? 'Nenhum nicho bom ainda' : 'Nenhum nicho com ' + fmt(minimo()) + ' trades ainda') + '</td></tr>';
    var m = mapa();
    rows.forEach(function (i, n) {
      var x = casas()[i], c = ramp(D.legendas.fr.paradas, x.fr), sub = dims(x).map(function (d) { return d[1]; }).join(', ');
      h += '<tr data-i="' + i + '"><td class="rk">' + (n + 1) + '</td>' +
        '<td><button type="button" class="b-nbtn" data-i="' + i + '" aria-label="Abrir nicho ' + esc(nome(x)) + '">' + esc(m.linhas[x.linha]) + '<span>' + esc(m.colunas[x.coluna]) + '</span></button><div class="b-sub" title="' + esc(sub) + '">' + esc(sub) + '</div></td>' +
        '<td><div class="b-seals">' + seals(x) + '</div></td>' +
        '<td class="num"><div class="b-frc"><span class="b-ibar" aria-hidden="true"><i style="width:' + Math.min(100, (x.fr == null ? 6 : Math.max(0, x.fr)) / 6 * 100).toFixed(0) + '%;background:' + css(c) + '"></i></span><b' + (fraco(x) ? ' class="neg"' : '') + '>' + frTxt(x) + '</b></div>' +
        (x.mediana != null ? '<div class="b-sub">mediana ' + dec(x.mediana, 1) + '</div>' : '') + '</td>' +
        '<td class="num">' + (x.pf == null ? '∞' : dec(x.pf, 2)) + '</td>' +
        '<td class="num"><div class="b-frc"><span class="b-ibar tr" aria-hidden="true"><i style="width:' + Math.min(100, x.trades / maxTr * 100).toFixed(0) + '%"></i></span>' + fmt(x.trades) + '</div></td>' +
        '<td class="num' + (x.membros != null && x.membros < 15 ? ' b-warn' : '') + '">' + (x.membros == null ? '—' : x.membros) + '</td>' +
        '<td>' + sparkSVG(x) + '</td></tr>';
    });
    $('b-lbody').innerHTML = h;
    if (foc !== null) { var t = $('b-lbody').querySelector('.b-nbtn[data-i="' + foc + '"]'); if (t) t.focus(); }
  }

  /* ------------------------------------------------------------ espaço */
  function numBR(s) {
    // "1.234,5" (pt-BR), "80.000" (milhar) e "1.5" (ponto decimal, o hábito dos outros campos)
    s = String(s == null ? '' : s).replace(/[^\d,.\-]/g, '');
    if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(',', '.');
    else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
    var v = parseFloat(s); return isNaN(v) ? null : v;
  }
  function numTxt(v) { return v == null ? '' : String(v).replace('.', ','); }
  function iniciarRasc() {
    rasc = {};
    D.espaco.itens.forEach(function (it) { rasc[it.nome] = JSON.parse(JSON.stringify(it.faixa)); });
    rasc._meta = D.criterio || 'fr'; rasc._min = D.minimo || 400;
  }
  function chips(it, ligados, todosLigados) {
    return it.opcoes.map(function (o) {
      return '<button type="button" class="b-chip" data-it="' + it.nome + '" data-v="' + esc(JSON.stringify(o.valor)) + '" aria-pressed="' + (ligados.indexOf(o.valor) >= 0) + '">' + esc(o.rotulo) + '</button>';
    }).join('');
  }
  function linhaItem(it) {
    var f = rasc[it.nome], h = '<tr><td class="it">' + esc(it.rotulo) + '</td><td>';
    if (it.tipo === 'lista' || it.tipo === 'dias') {
      h += '<div class="b-chips">' + chips(it, f.ligados || []) + (it.tipo === 'dias' ? q('Ajuda sobre dias', 'Testa qualquer combinação dos dias marcados (31 no total): só terça, segunda e quarta, de terça a quinta etc.') : '') + '</div></td><td class="b-dim">—</td></tr>';
      return h;
    }
    if (it.tipo === 'hora') {
      h += '<span class="b-rng"><span class="b-dim">de</span><input class="b-inp w-time" data-it="janela" data-k="de" value="' + esc(f.de) + '" aria-label="Horário de entrada, de"><span class="b-dim">até</span><input class="b-inp w-time" data-it="janela" data-k="ate" value="' + esc(f.ate) + '" aria-label="Horário de entrada, até">' +
        q('Ajuda sobre horário de entrada', 'A busca testa janelas de entrada dentro deste horário, de ' + f.minima + ' min para cima, começando e terminando a cada passo.') + '</span></td>' +
        '<td><input class="b-inp" data-it="janela" data-k="passo" value="' + f.passo + ' min" aria-label="Passo do horário de entrada"></td></tr>';
      return h;
    }
    if (it.tipo === 'gestao') {
      // uma linha por tipo: liga/desliga o tipo e edita de, até e passo
      var nomeTipo = {pontos: 'pontos', atr: 'ATR', percentual: 'porcentagem', multiplicador: 'vezes o stop', sem: 'sem alvo'};
      return it.opcoes.map(function (o, k) {
        var ft = f.tipos[o.tipo] || {}, alvo = esc(it.rotulo.toLowerCase()) + ' em ' + (nomeTipo[o.tipo] || o.tipo);
        var lin = '<tr>' + (k === 0 ? '<td class="it" rowspan="' + it.opcoes.length + '">' + esc(it.rotulo) + '</td>' : '') +
          '<td><span class="b-rng"><button type="button" class="b-chip" data-it="' + it.nome + '" data-tipo="' + o.tipo + '" aria-pressed="' + !!ft.on + '">' + esc(o.rotulo) + '</button>';
        if (o.tipo === 'sem') return lin + '</span></td><td class="b-dim">—</td></tr>';
        return lin + '<input class="b-inp w-s" data-it="' + it.nome + '" data-tipo="' + o.tipo + '" data-k="de" value="' + numTxt(ft.de) + '" aria-label="' + alvo + ', mínimo"><span class="b-dim">a</span>' +
          '<input class="b-inp w-s" data-it="' + it.nome + '" data-tipo="' + o.tipo + '" data-k="ate" value="' + numTxt(ft.ate) + '" aria-label="' + alvo + ', máximo"></span></td>' +
          '<td><input class="b-inp w-s" data-it="' + it.nome + '" data-tipo="' + o.tipo + '" data-k="passo" value="' + numTxt(ft.passo) + '" aria-label="Passo do ' + alvo + '"></td></tr>';
      }).join('');
    }
    h += '<span class="b-rng"><input class="b-inp w-s" data-it="' + it.nome + '" data-k="de" value="' + numTxt(f.de) + '" aria-label="' + esc(it.rotulo) + ', mínimo"><span class="b-dim">a</span><input class="b-inp w-s" data-it="' + it.nome + '" data-k="ate" value="' + numTxt(f.ate) + '" aria-label="' + esc(it.rotulo) + ', máximo"></span></td>';
    h += it.degrau === 'proporcional'
      ? '<td><span class="b-cy">proporcional</span>' + q('Ajuda sobre passo proporcional', 'Passo que cresce com o valor: perto de zero testa 2, 3, 4, 5; lá em cima pula de uns 8 em 8.', 'r') + '</td></tr>'
      : '<td><input class="b-inp w-s" data-it="' + it.nome + '" data-k="passo" value="' + numTxt(f.passo) + '" aria-label="Passo de ' + esc(it.rotulo) + '"></td></tr>';
    return h;
  }
  function renderEsp() {
    if (!rasc) iniciarRasc();
    var E = D.espaco, h = '<div class="b-cfgtop"><div class="b-blk"><h3>Regras</h3><div class="b-fl">' +
      '<div><label for="b-r-crit">Meta</label><select id="b-r-crit" class="b-dd" style="width:200px">' + D.metas.map(function (m) { return '<option value="' + m.valor + '"' + (m.valor === rasc._meta ? ' selected' : '') + '>' + esc(m.rotulo) + '</option>'; }).join('') + '</select></div>' +
      '<div><label for="b-r-min">Mín. de trades</label><span style="display:inline-flex;align-items:center"><input id="b-r-min" class="b-inp" value="' + rasc._min + '" inputmode="numeric">' + q('Ajuda sobre mínimo de trades', 'Abaixo disso o nicho fica listrado no mapa. 400 é o padrão: com menos de uns 300 trades o resultado tende a ser sorte.') + '</span></div></div></div>' +
      '<div class="b-blk"><h3>Fixos' + q('Ajuda sobre fixos', 'Valem iguais para todas as combinações. Para mudar, ajuste no menu antes de iniciar.') + '</h3><div class="b-kv">' +
      E.fixos.map(function (f) { return '<div><span>' + esc(f[0]) + '</span><b>' + esc(f[1]) + '</b></div>'; }).join('') + '</div></div></div>' +
      '<div class="b-blk" style="padding:2px 4px"><table class="b-t"><thead><tr><th scope="col" style="width:200px">Item</th><th scope="col">Faixa</th><th scope="col" style="width:200px">Passo' + q('Ajuda sobre passo', 'De quanto em quanto o valor anda dentro da faixa. Exemplo: horário de 09:30 a 16:00 com passo de 30 min testa 09:30, 10:00, 10:30 e assim por diante.', 'r') + '</th></tr></thead><tbody>' +
      E.itens.filter(function (it) { return it.onde !== 'param'; }).map(linhaItem).join('') + '</tbody><tbody>' +
      E.itens.filter(function (it) { return it.onde === 'param'; }).map(linhaItem).join('') + '</tbody></table></div>';
    $('b-cfg-corpo').innerHTML = h;
    initTips($('b-cfg-corpo'));
    // o fieldset fica ativo: desligá-lo desligaria também os (?) de dentro
    $$('#b-cfg input,#b-cfg select,#b-cfg .b-chip').forEach(function (el) { el.disabled = !!E.travado; });
    $('b-cfg-lock').hidden = !E.travado; $('b-esp-lock').style.display = E.travado ? '' : 'none';
  }
  function renderEspTrava() {
    var t = !!D.espaco.travado;
    $$('#b-cfg input,#b-cfg select,#b-cfg .b-chip').forEach(function (el) { el.disabled = t; });
    $('b-cfg-lock').hidden = !t; $('b-esp-lock').style.display = t ? '' : 'none';
  }
  function lerEsp() {
    var faixas = {};
    D.espaco.itens.forEach(function (it) {
      var f = JSON.parse(JSON.stringify(rasc[it.nome]));
      if (it.tipo === 'hora') { f.passo = parseInt(f.passo, 10); f.minima = parseInt(f.minima, 10); }
      faixas[it.nome] = f;
    });
    return faixas;
  }

  /* ------------------------------------------------------------ trilho */
  function cpuTotal() { return (D && D.cpu_total) || 24; }
  function cpuDefault() { return $('b-c-hora').checked ? Math.min(20, cpuTotal()) : 4; }
  function setCpu(n, manual) {
    var tot = cpuTotal(); n = Math.max(1, Math.min(tot, Math.round(n) || 1));
    $('b-n-cpu').value = n; $('b-cpu-m').disabled = n <= 1; $('b-cpu-p').disabled = n >= tot;
    if (manual) cpuTouched = n !== cpuDefault();
    $('b-cpu-def').hidden = !cpuTouched; $('b-cpu-de').textContent = 'de ' + tot;
    var h = ''; for (var i = 0; i < tot; i++) h += '<i class="' + (i < n ? 'on' : '') + '"></i>'; $('b-cpubar').innerHTML = h;
    $('b-cpubar').style.gridTemplateColumns = 'repeat(' + tot + ',1fr)';
    if (manual && D && D.busca_id && ['rodando', 'pausada'].indexOf(status()) >= 0) { acao('ajustar', {campos: {nucleos: n}}); $('b-cpu-ap').hidden = false; }
  }
  function ctlAtual() {
    var lim = $('b-c-lim').checked ? numBR($('b-i-lim').value) : null;
    return {nucleos: +$('b-n-cpu').value, parar_as: $('b-i-hora').value || '08:30', parar_as_ligado: $('b-c-hora').checked, limite: lim};
  }
  function renderSaved() {
    var ul = $('b-saved'), sv = D.salvas || [];
    if (!sv.length) { ul.innerHTML = '<li class="b-dim" style="padding:6px 8px">Nenhuma busca salva</li>'; return; }
    ul.innerHTML = sv.map(function (s) {
      var pl = STPILL[s.status] || STPILL.parada, locked = s.status === 'rodando';
      var tip = locked ? 'Pause ou pare a busca para excluir' : 'Excluir a busca #' + s.id;
      return '<li><button type="button" class="b-sv" data-id="' + s.id + '"' + (D.busca_id === s.id ? ' aria-current="true"' : '') + ' aria-label="Busca #' + s.id + ', de ' + s.data + ', ' + pl[1] + '"><span class="n">#' + s.id + '</span><span class="d">' + s.data + '</span><span class="b-pill ' + pl[0] + ' sm">' + pl[1] + '</span></button>' +
        '<button type="button" class="b-ico del" data-del="' + s.id + '" aria-label="' + tip + '" data-tip="' + tip + '"' + (locked ? ' aria-disabled="true"' : '') + '>' + TRASH + '</button></li>';
    }).join('');
  }

  /* ------------------------------------------------------------ faixa */
  function renderStrip() {
    var m = mapa(), s = st(), crit = D.criterio || 'fr', sig = D.sigla || 'FR';
    $('b-k-t').textContent = D.testes || '—'; $('b-k-tde').textContent = D.de_txt || '';
    var pct = D.barra || 0; $('b-k-barf').style.width = pct + '%'; $('b-k-bar').className = 'b-bar ' + s.barc; $('b-k-bar').setAttribute('aria-valuenow', pct);
    $('b-k-n').textContent = m ? m.n_com_resultado : '—'; $('b-k-nde').textContent = m ? 'de ' + m.n_casas : '';
    $('b-k-b').textContent = m && m.bons != null ? m.bons : '—';
    var best = m && m.melhor; $('b-k-bl').textContent = 'Melhor ' + sig;
    var bv = !best ? '—' : crit === 'pf' ? (best.pf == null ? '∞' : dec(best.pf, 2))
      : crit === 'lucro' ? moeda(best.objetivo) : crit === 'dd' ? moeda(-best.objetivo) : frTxt(best);
    $('b-k-fr').textContent = bv; $('b-k-best').disabled = !best;
    $('b-k-best').setAttribute('aria-label', best ? 'Melhor ' + sig + ' ' + bv + ', ir até ele no mapa' : 'Sem melhor ainda');
    $('b-k-dec').textContent = D.decorrido || '—'; $('b-k-fal').textContent = D.faltam || ''; $('b-k-tl').textContent = D.rotulo_tempo || 'Decorrido';
    var hs = D.historico || [];
    if (hs.length > 1) {
      var t0 = hs[0][0], t1 = hs[hs.length - 1][0] || 1, mx = Math.max.apply(null, hs.map(function (p) { return p[1]; })) || 1;
      $('b-k-sparkl').setAttribute('points', hs.map(function (p) { return ((p[0] - t0) / (t1 - t0 || 1) * 200).toFixed(1) + ',' + (21 - p[1] / mx * 17).toFixed(1); }).join(' '));
      $('b-k-spark').style.visibility = 'visible';
    } else $('b-k-spark').style.visibility = 'hidden';
    var nomeMeta = crit === 'fr' ? 'fator de recuperação 3 ou mais' : (crit === 'pf' ? 'profit factor 1,25 ou mais' : '');
    setTip($('b-q-nichos'), 'Nichos com ' + fmt(minimo()) + ' trades ou mais já achados, do total de casas desta visão do mapa. A busca é premiada por acender nichos novos, não só por melhorar o melhor.');
    setTip($('b-q-bons'), nomeMeta ? 'Nichos com ' + nomeMeta + '. ' + (crit === 'fr' ? 'Acima de 3: bom. Abaixo de 1,5: fraco.' : '') : 'Sem corte de "bom" para esta meta.');
    setTip($('b-q-melhor'), 'Maior ' + (crit === 'pf' ? 'profit factor' : 'fator de recuperação (lucro dividido pela maior queda)') + ' até agora. Clique no número para ir até ele no mapa.');
    $('b-sw-min').textContent = 'menos de ' + fmt(minimo()) + ' trades';
  }

  /* ------------------------------------------------------------ aplicar */
  var ultimoStatus = null, ultimoStatusFoco = undefined, ultimaBusca = undefined, formaMapa = '', chaveEsp = '', versaoGrupos = null;
  var salvasJson = '', casaJson = '', feitoVisto = null, avisoT = null, focoDepois = null;
  function apply() {
    var s = st(), nomeSt = status();
    $('b-st-pill').className = 'b-pill lg ' + s.pill; $('b-st-spin').hidden = !s.spin; $('b-st-txt').textContent = s.txt;
    $('b-st-when').textContent = D.quando || ''; $('b-st-when').hidden = !D.quando; setTip($('b-st-q'), D.dica || '');
    if (ultimoStatus !== null && ultimoStatus !== nomeSt) $('b-st-live').textContent = 'Busca ' + s.txt.toLowerCase();
    ['ini', 'pau', 'con', 'par', 'nova'].forEach(function (k) { $('b-' + k).disabled = !s.b[k]; });
    root.classList.toggle('is-running', !!s.live);
    $('b-live').hidden = !s.live;
    var tem = !!mapa() && mapa().n_casas > 0 && (D.testes || '0') !== '0';
    $('b-map-empty').hidden = tem; $('b-map-has').hidden = !tem; $('b-mapctl').hidden = !tem;
    $('b-l-empty').hidden = tem; $('b-l-has').hidden = !tem;
    // com a busca já rodando, o vazio é só espera: nada de "Iniciar busca"
    $$('[data-go="ini"]').forEach(function (b) { b.hidden = nomeSt !== 'parada'; });
    var chave = D.busca_id + '|' + D.estrategia + '|' + D.simbolo;
    // o rascunho do espaço é da estratégia e do ativo: trocou o menu, refaz
    if (chave !== chaveEsp) { rasc = null; chaveEsp = chave; }
    if (D.versao_grupos !== versaoGrupos) { detCache = {}; pedidos = {}; versaoGrupos = D.versao_grupos; }
    if (D.busca_id !== ultimaBusca) {           // trocou de busca: refaz tudo
      rasc = null; detCache = {}; pedidos = {}; if (drOpen) closeDr();
      var c = D.controle || {};
      $('b-c-hora').checked = c.parar_as_ligado !== false; $('b-i-hora').value = c.parar_as || '08:30'; $('b-i-hora').disabled = !$('b-c-hora').checked;
      $('b-c-lim').checked = !!c.limite; $('b-i-lim').disabled = !c.limite; $('b-i-lim').value = c.limite ? fmt(c.limite) : '—';
      cpuTouched = false; setCpu(c.nucleos || cpuDefault(), false);
      if (nomeSt === 'parada') setView('esp'); else if (view === 'esp' && ultimaBusca === null) setView('mapa');
    } else if ((D.controle || {}).nucleos && +$('b-n-cpu').value === D.controle.nucleos) $('b-cpu-ap').hidden = true;
    setTip($('b-q-cpu'), 'Quantos dos ' + cpuTotal() + ' núcleos a busca usa. Mais é mais rápido, mas o PC fica pesado. Padrão: ' + Math.min(20, cpuTotal()) + ' com Parar às ligado (noite), 4 com ele desligado (você usando o PC). Vale em poucos segundos, mesmo rodando.');
    ultimaBusca = D.busca_id; ultimoStatus = nomeSt;
    renderStrip();
    // o mapa só é refeito quando muda de forma; senão repinta as casas (o
    // foco do teclado e o tooltip sobrevivem à atualização de 2 s)
    var m = mapa(), forma = m ? D.busca_id + '|' + axis + '|' + m.linhas.length + 'x' + m.colunas.length : '';
    if (m) { if (forma !== formaMapa) renderMap(); else { renderLegend(); paint(); } if (view === 'lista') renderList(); }
    formaMapa = forma;
    if (!rasc || !$('b-cfg-corpo').innerHTML) renderEsp(); else renderEspTrava();
    // só redesenha o que mudou: a cada 2 s o foco do teclado não pode sumir
    var sj = JSON.stringify(D.salvas || []) + D.busca_id;
    if (sj !== salvasJson) { salvasJson = sj; renderSaved(); }
    if (D.feito && D.feito !== feitoVisto) {
      feitoVisto = D.feito; $('b-svmsg').textContent = D.aviso || '';
      clearTimeout(avisoT); avisoT = setTimeout(function () { $('b-svmsg').textContent = ''; }, 4000);
    }
    if (drOpen) {
      var cx = casas()[di];
      if (!abre(cx)) closeDr();
      else { var cj = JSON.stringify(cx) + status(); if (cj !== casaJson) { casaJson = cj; fillDrawer(); } }
    }
    // depois de uma ação o botão clicado se desliga: o foco vai ao próximo útil
    var ae = document.activeElement;
    if (focoDepois === 'salvas') { focoDepois = null; var sv = $('b-saved').querySelector('.b-sv'); (sv || $('b-ini')).focus(); }
    else if (ultimoStatusFoco !== nomeSt && (!ae || ae === document.body || ae.disabled) && root.contains(ae || root)) {
      var alvo = ['b-con', 'b-pau', 'b-ini', 'b-nova'].map($).filter(function (b) { return b && !b.disabled; })[0];
      if (alvo && ultimoStatusFoco !== undefined) alvo.focus();
    }
    ultimoStatusFoco = nomeSt;
  }

  /* ------------------------------------------------------------ visão */
  var TABS = [['mapa', 'b-v-mapa', 'b-p-mapa'], ['lista', 'b-v-lista', 'b-p-lista'], ['esp', 'b-v-esp', 'b-p-esp']];
  function setView(v, focusTab) {
    view = v; hideTip();
    TABS.forEach(function (a) { var t = $(a[1]), on = a[0] === v; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; $(a[2]).hidden = !on; if (on && focusTab) t.focus(); });
    if (v === 'lista') renderList();
  }

  /* ------------------------------------------------------------ gaveta */
  function order() {
    if (view === 'lista') return listRows();
    var o = []; casas().forEach(function (x, i) { if (abre(x)) o.push(i); }); return o;
  }
  function moeda(v) { return (D.moeda ? D.moeda + ' ' : '') + fmt(v); }
  function heatHTML(hd) {
    var base = hx('#111113'), h = '<table class="b-heat"><caption class="b-sr">Resultado médio por trade, por hora de entrada e dia</caption><thead><tr><td></td>' + hd.dias.map(function (d) { return '<th scope="col">' + d + '</th>'; }).join('') + '</tr></thead><tbody>';
    hd.horas.forEach(function (hr, ri) {
      h += '<tr><th scope="row">' + hr + '</th>';
      hd.dias.forEach(function (d, dj) {
        var v = hd.valores[ri][dj], dentro = hd.dentro[ri][dj];
        if (v == null) { h += '<td class="na' + (dentro ? ' in' : '') + '" title="menos de 40 trades">—</td>'; return; }
        var a = Math.min(Math.abs(v) / 20, 1) * 0.75 + 0.12, c = Math.round(v) === 0 ? hx('#1c1c20') : mix(hx(v > 0 ? '#00F5A0' : '#FF4D7D'), base, a);
        h += '<td class="' + (dentro ? 'in' : '') + '" style="background:' + css(c) + ';color:' + ink(c) + '">' + (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v)) + '</td>';
      });
      h += '</tr>';
    });
    return h + '</tbody></table><div class="b-hleg"><span><i style="background:#00b679"></i>ganha</span><span><i style="background:#c23a64"></i>perde</span><span><i style="box-shadow:inset 0 0 0 1.5px #22E4FF"></i>região do nicho</span><span>' + esc(D.moeda || '') + ' por trade</span></div>';
  }
  function yearsHTML(anos) {
    var h = '<div class="b-yrs" style="grid-template-columns:repeat(' + Math.max(anos.length, 1) + ',1fr)">';
    anos.forEach(function (a) {
      if (a.holdout || a.pct_lucro == null) { h += '<div class="b-yr ho"><span class="v b-dim">—</span><span class="bt" aria-hidden="true"></span><span class="y">' + a.ano + '</span></div>'; return; }
      var p = a.pct_lucro, cl = p >= 70 ? 'pos' : (p >= 50 ? 'warn' : 'neg'), col = p >= 70 ? '#00F5A0' : (p >= 50 ? '#FFC93C' : '#FF4D7D');
      h += '<div class="b-yr"><span class="v b-' + cl + '">' + p + '%</span><span class="bt" aria-hidden="true"><i style="height:' + p + '%;background:' + col + ';opacity:.75"></i></span><span class="y">' + a.ano + '</span></div>';
    });
    return h + '</div>';
  }
  function spreadHTML(itens) {
    function v(x) { return typeof x === 'number' ? (x % 1 ? dec(x, x * 100 % 10 ? 2 : 1) : String(x)) : esc(x); }
    var h = '<table class="b-t"><caption class="b-sr">Espalhamento dos parâmetros entre os membros</caption><thead><tr><th scope="col">Item</th><th scope="col" style="width:150px">Faixa dos membros</th><th scope="col"></th><th scope="col" class="num">Mediana</th><th scope="col" class="num">Campeão</th></tr></thead><tbody>';
    itens.forEach(function (p) {
      var a = p.testada[0], z = p.testada[1], w = (z - a) || 1, L = (p.membros[0] - a) / w * 100, W = (p.membros[1] - p.membros[0]) / w * 100, C = (p.campeao - a) / w * 100;
      h += '<tr><td class="it">' + esc(p.item) + '</td><td><span class="b-rg" aria-hidden="true"><i class="m" style="left:' + L.toFixed(1) + '%;width:' + W.toFixed(1) + '%"></i><i class="c" style="left:' + C.toFixed(1) + '%"></i></span></td>' +
        '<td style="white-space:nowrap">' + v(p.membros[0]) + ' a ' + v(p.membros[1]) + '</td><td class="num">' + v(p.mediana) + '</td><td class="num b-cy">' + v(p.campeao) + '</td></tr>';
    });
    return h + '</tbody></table><div class="b-hleg"><span><i style="background:#1d1d22"></i>faixa testada</span><span><i style="background:rgba(34,228,255,.55)"></i>membros</span><span><i style="background:#fff;width:2px"></i>campeão</span></div>';
  }
  function curveHTML(cv) {
    var y = cv.y || [], n = y.length; if (n < 2) return '<p class="b-dim">Sem trades no período</p>';
    var mn = Math.min(0, Math.min.apply(null, y)), mx = Math.max.apply(null, y), W = 640, H = 150, pad = 18;
    var sx = function (i) { return 46 + i * (W - 56) / (n - 1); }, sy = function (v) { return pad + (H - pad * 2) * (1 - (v - mn) / ((mx - mn) || 1)); };
    var line = y.map(function (v, i) { return sx(i).toFixed(1) + ',' + sy(v).toFixed(1); }).join(' ');
    var g = ''; [0, 0.5, 1].forEach(function (f) { var yy = pad + (H - pad * 2) * f; g += '<line x1="46" x2="' + W + '" y1="' + yy + '" y2="' + yy + '" stroke="#1d1d22"/>'; });
    var anos = {}, xl = ''; cv.x.forEach(function (d, i) { var a = d.slice(0, 4); if (!(a in anos)) { anos[a] = i; xl += '<text x="' + sx(i).toFixed(0) + '" y="' + (H - 2) + '" text-anchor="middle" fill="#8B8B93" font-size="10">' + a + '</text>'; } });
    var yl = '<text x="46" y="' + (pad - 6) + '" text-anchor="start" fill="#8B8B93" font-size="10">' + esc(Math.abs(mx) >= 1000 ? (D.moeda ? D.moeda + ' ' : '') + fmt(mx / 1000) + ' mil' : moeda(mx)) + '</text><text x="40" y="' + (sy(0) + 4).toFixed(0) + '" text-anchor="end" fill="#8B8B93" font-size="10">0</text>';
    return '<svg class="b-curve" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Curva de capital do campeão: termina em ' + esc(moeda(y[n - 1])) + '">' + g +
      '<polygon points="' + sx(0) + ',' + sy(mn) + ' ' + line + ' ' + sx(n - 1) + ',' + sy(mn) + '" fill="rgba(0,245,160,.07)"/><polyline fill="none" stroke="#00F5A0" stroke-width="1.8" stroke-linejoin="round" points="' + line + '"/>' + yl + xl + '</svg>';
  }
  function kpi(l, v, cls, extra) { return '<div class="b-kpi"><span class="l">' + l + (extra || '') + '</span><b' + (cls ? ' class="' + cls + '"' : '') + '>' + v + '</b></div>'; }
  function fillDrawer() {
    casaJson = JSON.stringify(casas()[di]) + status();
    var x = casas()[di], m = mapa(), ord = order(), p = ord.indexOf(di), det = detCache[x.casa_fina];
    $('b-dr-tf').textContent = m.linhas[x.linha]; $('b-dr-cv').textContent = m.colunas[x.coluna];
    var pills = dims(x).map(function (d) { return '<span class="b-pill gray sm"><span class="b-dim" style="font-weight:400">' + esc(d[0].toLowerCase()) + '</span>' + esc(d[1]) + '</span>'; }).join('');
    if (x.melhor) pills += '<span class="b-pill cy sm">★ melhor do mapa</span>';
    if (bom(x)) pills += '<span class="b-pill green sm">bom</span>'; else if (fraco(x)) pills += '<span class="b-pill rose sm">fraco</span>';
    if (status() === 'rodando') pills += '<span class="b-pill amber sm">parcial</span>' + q('Ajuda sobre parcial', 'A busca ainda está rodando: o nicho pode achar resultado melhor e os números podem mudar.');
    $('b-dr-pills').innerHTML = pills;
    navBtn($('b-dr-prev'), ord[p - 1], 'anterior'); navBtn($('b-dr-next'), ord[p + 1], 'seguinte');
    $('b-dr-pos').textContent = (p + 1) + ' de ' + ord.length;
    var k = det && !det.erro ? det.kpis : null, kfr = ramp(D.legendas.fr.paradas, x.fr), membros = k ? k.membros : x.membros;
    var carregando = '<p class="b-dim">carregando…</p>';
    $('b-dr-body').innerHTML =
      '<div class="b-kpis">' +
        kpi('<i style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;background:' + css(kfr) + '"></i>FR', frTxt(x), 'cy') +
        kpi('FR mediano', k && k.fr_mediano != null ? dec(k.fr_mediano, 1) : (crit() === 'fr' && x.mediana != null ? dec(x.mediana, 1) : '—'), '', q('Ajuda sobre FR mediano', 'Mediana do FR dos membros. Perto do FR do campeão indica região sólida, não um ponto de sorte.')) +
        kpi('PF', x.pf == null ? '∞' : dec(x.pf, 2)) + kpi('Trades', fmt(x.trades)) +
        kpi('Maior queda', k && k.maior_queda != null ? esc(moeda(k.maior_queda)) : '—') +
        kpi('Membros', membros == null ? '—' : membros, membros != null && membros < 15 ? 'warn' : '', q('Ajuda sobre membros', 'Combinações parecidas que também passaram. Menos de 15 pode ser pico isolado.', 'r')) +
      '</div><div class="b-dgrid">' +
        '<div class="b-blk"><h3>Hora × dia' + q('Ajuda sobre hora por dia', 'Resultado médio por trade (' + (D.moeda || '') + ') dos membros, por hora de entrada e dia. Contorno ciano: região do nicho. Traço: menos de 40 trades.') + '</h3>' + (det && !det.erro ? heatHTML(det.hora_dia) : carregando) + '</div>' +
        '<div class="b-blk"><h3>Por ano' + q('Ajuda sobre por ano', 'Quantos % dos membros fecharam o ano no lucro. Acima de 70% bom; abaixo de 50% ano fraco. O holdout fica de fora.', 'r') + '</h3>' + (det && !det.erro ? yearsHTML(det.por_ano) : carregando) + '</div>' +
        '<div class="b-blk wide"><h3>Espalhamento' + q('Ajuda sobre espalhamento', 'Até onde vão os parâmetros entre os membros, dentro da faixa testada. Faixa larga com mediana boa: região robusta.') + '</h3>' + (det && !det.erro ? spreadHTML(det.espalhamento) : carregando) + '</div>' +
        '<div class="b-blk wide"><h3>Curva do campeão</h3>' + (det && !det.erro ? curveHTML(det.curva) : (det && det.erro ? '<p class="b-warn">' + esc(det.erro) + '</p>' : carregando)) + '</div>' +
      '</div>';
    var ok = !!D.menu_ok; $('b-dr-bt').disabled = !ok; $('b-dr-min').disabled = !ok;
    initTips($('b-drawer'));
    // um pedido por casa: a tela se redesenha a cada 2 s com a busca rodando
    if (det && det.erro) { delete detCache[x.casa_fina]; delete pedidos[x.casa_fina]; }
    if ((!det || det.erro) && !pedidos[x.casa_fina]) { pedidos[x.casa_fina] = 1; pedidoN++; enviar('busca-pedido', {id: D.busca_id, casa: x.casa_fina, pedido: pedidoN}); }
  }
  function navBtn(b, i, word) {
    if (i === undefined) { b.disabled = true; b.setAttribute('aria-label', 'Sem nicho ' + word); b.setAttribute('data-tip', 'Sem nicho ' + word); return; }
    b.disabled = false; var t = 'Nicho ' + word + ': ' + nome(casas()[i]) + ' (seta ' + (word === 'anterior' ? '←' : '→') + ')';
    b.setAttribute('aria-label', t); b.setAttribute('data-tip', t); b._to = i;
  }
  function setInert(on) {
    // o menu e as subtelas do app ficam fora para o leitor de tela também
    [document.getElementById('sidebar'), document.querySelector('.mine-subtelas')].forEach(function (el) {
      if (!el) return; el.inert = on; if (on) el.setAttribute('aria-hidden', 'true'); else el.removeAttribute('aria-hidden');
    });
    Array.prototype.forEach.call(root.children, function (ch) {
      if (ch === $('b-drawer') || ch === $('b-cf') || ch === $('b-scrim') || ch === $('b-tip')) return;
      ch.inert = on; if (on) ch.setAttribute('aria-hidden', 'true'); else ch.removeAttribute('aria-hidden');
    });
  }
  function openDr(i) {
    if (!abre(casas()[i])) return;
    di = i;
    if (!drOpen) {
      lastFocus = document.activeElement; drOpen = true; hideTip();
      setInert(true); $('b-scrim').hidden = false; $('b-drawer').hidden = false; fillDrawer();
      void $('b-drawer').offsetWidth; $('b-drawer').classList.add('b-in');
      $('b-dr-ttl').focus();
    } else fillDrawer();
  }
  function goNb(dir) {
    var b = dir < 0 ? $('b-dr-prev') : $('b-dr-next'); if (b.disabled) return;
    di = b._to; fillDrawer(); $('b-dr-live').textContent = 'Nicho ' + nome(casas()[di]);
    if (b.disabled) $('b-dr-ttl').focus();
  }
  function closeDr() {
    if (!drOpen) return; drOpen = false;
    $('b-drawer').classList.remove('b-in'); setInert(false); $('b-scrim').hidden = true;
    setTimeout(function () { if (!drOpen) $('b-drawer').hidden = true; }, reduce ? 0 : 230);
    var t = null;
    if (view === 'mapa') { focusCell(di); t = document.activeElement; }
    else if (view === 'lista') { t = $('b-lbody').querySelector('.b-nbtn[data-i="' + di + '"]'); if (t) t.focus(); }
    if (!t && lastFocus && lastFocus.focus) lastFocus.focus();
  }
  function focusables(el) { return $$('button,[href],input,select,textarea,[tabindex]', el).filter(function (n) { return !n.disabled && n.tabIndex >= 0 && n.offsetParent !== null; }); }
  function trap(e, el) {
    if (e.key !== 'Tab') return;
    var f = focusables(el); if (!f.length) return;
    var a = f[0], z = f[f.length - 1], act = document.activeElement;
    if (e.shiftKey && (act === a || f.indexOf(act) < 0)) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && (act === z || f.indexOf(act) < 0)) { e.preventDefault(); a.focus(); }
  }

  /* ------------------------------------------------------------ confirmação */
  function openCf(id, opener) {
    var s = (D.salvas || []).filter(function (z) { return String(z.id) === String(id); })[0]; if (!s) return;
    delId = s.id; cfOpener = opener;
    $('b-cf-t').textContent = 'Excluir a busca #' + s.id + '?';
    $('b-cf-d').textContent = 'Os ' + s.testes + ' testes e o mapa dela somem. Não dá para desfazer.';
    setInert(true); $('b-scrim').hidden = false; $('b-cf').hidden = false; $('b-cf-no').focus();
  }
  function closeCf(done) {
    $('b-cf').hidden = true; $('b-scrim').hidden = true; setInert(false);
    if (done) { focoDepois = 'salvas'; acao('excluir', {id: delId}); }
    else if (cfOpener && root.contains(cfOpener)) cfOpener.focus();
    delId = null;
  }

  /* ------------------------------------------------------------ eventos */
  function ligar() {
    var map = $('b-map');
    map.addEventListener('click', function (e) { var b = e.target.closest('.b-cell'); if (b && abre(casas()[+b.dataset.i])) { hideTip(); openDr(+b.dataset.i); } });
    map.addEventListener('mouseover', function (e) { var b = e.target.closest('.b-cell'); if (b) showTip(b); });
    map.addEventListener('mouseleave', function () { if (!map.contains(document.activeElement)) hideTip(); });
    map.addEventListener('focusin', function (e) { var b = e.target.closest('.b-cell'); if (b) showTip(b); });
    map.addEventListener('focusout', function () { setTimeout(function () { if (!map.contains(document.activeElement)) hideTip(); }, 0); });
    map.addEventListener('keydown', function (e) {
      var b = e.target.closest('.b-cell'); if (!b) return;
      var i = +b.dataset.i, n = nc(), r = Math.floor(i / n), c = i % n, j = null, nr = mapa().linhas.length;
      switch (e.key) {
        case 'ArrowRight': if (c < n - 1) j = i + 1; break;
        case 'ArrowLeft': if (c > 0) j = i - 1; break;
        case 'ArrowDown': if (r < nr - 1) j = i + n; break;
        case 'ArrowUp': if (r > 0) j = i - n; break;
        case 'Home': j = e.ctrlKey ? 0 : r * n; break;
        case 'End': j = e.ctrlKey ? casas().length - 1 : r * n + n - 1; break;
        case 'Enter': case ' ': if (abre(casas()[i])) { e.preventDefault(); hideTip(); openDr(i); } return;
        case 'Escape': hideTip(); return;
        default: return;
      }
      e.preventDefault(); if (j !== null) focusCell(j);
    });
    window.addEventListener('scroll', function () { var t = $('b-tip'); if (t && !t.hidden && t._cell) showTip(t._cell); }, true);

    $('b-lbody').addEventListener('click', function (e) { var tr = e.target.closest('tr[data-i]'); if (tr) openDr(+tr.dataset.i); });
    $('b-lbody').addEventListener('keydown', function (e) {
      var b = e.target.closest('.b-nbtn'); if (!b || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
      var all = $$('.b-nbtn', $('b-lbody')), k = all.indexOf(b) + (e.key === 'ArrowDown' ? 1 : -1);
      if (all[k]) { e.preventDefault(); all[k].focus(); }
    });
    $$('.b-sort').forEach(function (b) { b.addEventListener('click', function () {
      var k = b.dataset.k; if (sortK === k) sortDir = -sortDir; else { sortK = k; sortDir = k === 'nicho' ? 1 : -1; }
      renderList(); b.focus();
    }); });
    $('b-l-good').addEventListener('click', function () { onlyGood = !onlyGood; this.setAttribute('aria-pressed', String(onlyGood)); renderList(); });
    $('b-l-all').addEventListener('click', function () { showAll = !showAll; renderList(); this.focus(); });

    TABS.forEach(function (a, k) {
      $(a[1]).addEventListener('click', function () { setView(a[0]); });
      $(a[1]).addEventListener('keydown', function (e) {
        var n = null; if (e.key === 'ArrowRight') n = (k + 1) % 3; else if (e.key === 'ArrowLeft') n = (k + 2) % 3; else if (e.key === 'Home') n = 0; else if (e.key === 'End') n = 2;
        if (n !== null) { e.preventDefault(); setView(TABS[n][0], true); }
      });
    });
    $$('input[name="b-axis"]').forEach(function (r) { r.addEventListener('change', function () { axis = this.value; if (drOpen) closeDr(); renderMap(); formaMapa = D.busca_id + '|' + axis + '|' + mapa().linhas.length + 'x' + mapa().colunas.length; if (view === 'lista') renderList(); }); });
    $('b-mt').addEventListener('change', function () { metric = this.value; renderLegend(); paint(); });
    $('b-k-best').addEventListener('click', function () { var i = casas().findIndex(function (x) { return x.melhor; }); if (i < 0) return; if (view !== 'mapa') setView('mapa'); focusCell(i); });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && drOpen && !$('b-drawer').contains(e.target)) { e.preventDefault(); closeDr(); }
    });
    var drawer = $('b-drawer');
    drawer.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); closeDr(); return; }
      var tag = (e.target.tagName || '').toUpperCase();
      if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && tag !== 'INPUT' && tag !== 'SELECT' && tag !== 'TEXTAREA') { e.preventDefault(); goNb(e.key === 'ArrowLeft' ? -1 : 1); return; }
      trap(e, drawer);
    });
    $('b-dr-close').addEventListener('click', closeDr);
    $('b-dr-prev').addEventListener('click', function () { goNb(-1); });
    $('b-dr-next').addEventListener('click', function () { goNb(1); });
    $('b-scrim').addEventListener('click', function () { if (drOpen) closeDr(); else if (!$('b-cf').hidden) closeCf(false); });
    $('b-dr-bt').addEventListener('click', function () { var x = casas()[di]; closeDr(); enviar('busca-ir', {acao: 'backtest', id: D.busca_id, casa: x.casa_fina}); });
    $('b-dr-min').addEventListener('click', function () { var x = casas()[di]; closeDr(); enviar('busca-ir', {acao: 'regiao', id: D.busca_id, casa: x.casa_fina}); });

    $('b-saved').addEventListener('click', function (e) {
      var d = e.target.closest('[data-del]');
      if (d) { if (d.getAttribute('aria-disabled') === 'true') return; openCf(d.dataset.del, d); return; }
      var b = e.target.closest('.b-sv'); if (!b) return;
      acao('abrir', {id: +b.dataset.id});
    });
    $('b-cf-no').addEventListener('click', function () { closeCf(false); });
    $('b-cf-yes').addEventListener('click', function () { closeCf(true); });
    $('b-cf').addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeCf(false); return; } trap(e, $('b-cf')); });

    function iniciar() { acao('iniciar', Object.assign({faixas: lerEsp(), criterio: rasc._meta, minimo: rasc._min}, ctlAtual())); }
    $$('[data-go="ini"]').forEach(function (b) { b.addEventListener('click', function () { if (status() === 'parada') iniciar(); else setView('esp'); }); });
    $('b-ini').addEventListener('click', iniciar);
    $('b-pau').addEventListener('click', function () { acao('pausar'); });
    $('b-con').addEventListener('click', function () { acao('continuar'); });
    $('b-par').addEventListener('click', function () { acao('parar'); });
    $('b-nova').addEventListener('click', function () { acao('nova'); });
    function ajustar(c) { if (D && D.busca_id && status() !== 'parada') acao('ajustar', {campos: c}); }
    $('b-c-hora').addEventListener('change', function () { $('b-i-hora').disabled = !this.checked; if (!cpuTouched) setCpu(cpuDefault(), false); ajustar({parar_as_ligado: this.checked}); });
    $('b-i-hora').addEventListener('change', function () { ajustar({parar_as: this.value}); });
    $('b-c-lim').addEventListener('change', function () { var i = $('b-i-lim'); i.disabled = !this.checked; i.value = this.checked ? '80.000' : '—'; if (this.checked) i.focus(); ajustar({limite: this.checked ? numBR(i.value) : null}); });
    $('b-i-lim').addEventListener('change', function () { ajustar({limite: numBR(this.value)}); });
    $('b-cpu-m').addEventListener('click', function () { setCpu(+$('b-n-cpu').value - 1, true); });
    $('b-cpu-p').addEventListener('click', function () { setCpu(+$('b-n-cpu').value + 1, true); });
    $('b-n-cpu').addEventListener('change', function () { setCpu(numBR(this.value), true); });
    $('b-cpu-def').addEventListener('click', function () { cpuTouched = false; setCpu(cpuDefault(), true); $('b-n-cpu').focus(); });

    // espaço de busca: chips e campos editam o rascunho
    $('b-cfg').addEventListener('click', function (e) {
      var c = e.target.closest('.b-chip'); if (!c || c.disabled || D.espaco.travado) return;
      var it = c.dataset.it, on = c.getAttribute('aria-pressed') !== 'true';
      c.setAttribute('aria-pressed', String(on));
      if (c.dataset.tipo) { rasc[it].tipos[c.dataset.tipo].on = on; return; }
      var v = JSON.parse(c.dataset.v), lig = rasc[it].ligados || (rasc[it].ligados = []);
      if (on && lig.indexOf(v) < 0) lig.push(v); if (!on) rasc[it].ligados = lig.filter(function (z) { return z !== v; });
    });
    $('b-cfg').addEventListener('change', function (e) {
      var t = e.target;
      if (t.id === 'b-r-crit') { rasc._meta = t.value; return; }
      if (t.id === 'b-r-min') { rasc._min = numBR(t.value) || 400; return; }
      var it = t.dataset.it, k = t.dataset.k; if (!it || !k) return;
      if (it === 'janela') { rasc.janela[k] = (k === 'de' || k === 'ate') ? t.value : (parseInt(t.value, 10) || rasc.janela[k]); return; }
      if (t.dataset.tipo) { rasc[it].tipos[t.dataset.tipo][k] = numBR(t.value); return; }
      rasc[it][k] = numBR(t.value);
    });
  }

  /* ------------------------------------------------------------ montagem */
  function montar() {
    var r = document.getElementById('busca-raiz');
    if (!r) return false;
    if (r.dataset.pronto) { root = r; return true; }
    r.innerHTML = esqueleto(); r.dataset.pronto = '1'; root = r;
    ligar(); initTips(root);
    return true;
  }
  window.buscaTela = {
    dados: function (d) {
      if (!d || !montar()) return;
      if (D && d.assinatura && d.assinatura === D.assinatura) return;   // nada mudou
      D = d; apply();
    },
    detalhe: function (d) {
      if (!d || !montar() || !d.casa) return;
      detCache[d.casa] = d;
      if (drOpen && casas()[di] && casas()[di].casa_fina === d.casa) fillDrawer();
    }
  };
})();
