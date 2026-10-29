# Ativos da CME — etapa 3 (moeda) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No caminho da pesquisa, todo valor em dinheiro sai na moeda do ativo (WIN "R$", MES/MNQ "US$"), e portfólio que misture moedas é recusado com mensagem.

**Architecture:**
- Uma função de formatação com moeda (`cartao.dinheiro`) substitui o `brl` fixo.
- Cada componente de tela ganha o argumento `moeda="BRL"`; o padrão reproduz a saída de hoje.
- Os callbacks passam a moeda do ativo em foco: `run["simbolo"]` no backtest, o símbolo guardado no estado da mineração, `_WFA["symbol"]` e `d["symbol"]`.
- Rótulos fixos do layout viram `html.Span` com id de padrão, um `type` por tela, atualizados por callback.
- O portfólio descobre a moeda de cada membro pelo `wfa_runs.symbol` do plano ativo.

**Tech Stack:** Python, Dash, dash-ag-grid, Plotly, DuckDB, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` (seção 8 "Moeda", D10, "Estado depois da etapa 2").

## Global Constraints

- **WIN idêntico.** Sem `moeda` (ou com `moeda="BRL"`), cada função de tela devolve exatamente o que devolve hoje.
  - A prova é a **referência de telas** gravada na Task 1, antes de qualquer edição. A foto do WIN (`scripts/foto_win.py`) só cobre o motor; ela continua sendo conferida no fim, mas não substitui a referência.
- **Símbolo do WIN é `"WIN$N"`** (não `"WIN"`). Sempre `ativo.ficha(simbolo)`. Um símbolo sem YAML cai em BRL, nunca em erro.
- **Caminho ao vivo fora de escopo e intocado:** `ao_vivo*`, `ordens*`, `operacao*`, `papel*`, `corretora*`, `captura.py`, `callbacks_ao_vivo.py`, `callbacks_operacao.py`, `ui/components/ao_vivo_panel.py`.
  - `brl()` e `ficha.ficha(...)` continuam com o mesmo comportamento, porque o ao vivo os usa (`ao_vivo_panel.py:860`).
- **Moeda e símbolo:**
  - A moeda vem de `Ficha.currency` (código ISO do YAML).
  - Símbolos: `"BRL" → "R$"`, `"USD" → "US$"`; código desconhecido → o próprio código (`"EUR 1,00"`).
  - Nome por extenso nas dicas: `"BRL" → "reais"`, `"USD" → "dólares"`, desconhecido → o código.
- **Número no formato brasileiro também em dólar:** `US$ 1.234,56`; negativo `-US$ 57.056,00`. A linha de comando (`core/metrics.format_panel`) mantém o alinhamento próprio e só troca o símbolo.
- **Regra da tela:** nenhum texto explicativo novo visível. Textos de (?) com "R$" ou "em reais" passam a usar a moeda, **quando o componente recebe `moeda`**. Os textos de layout fixo montados uma vez ficam como estão, e cada um é anotado no ledger:
  - `mine_criterios` / `core/mineracao_stats.py:32`;
  - `core/porteira.py:72, 190`;
  - `core/tamanho.py:421`.
- **Arquivos protegidos:**
  - `ui/components/controls.py`: mudança mínima autorizada (D11), só os 4 rótulos. Avisar o usuário no relatório.
  - `ui/components/wfa_matriz.py`: não editar.
- **Banco e portões salvos:** nada muda no banco nem no formato dos portões salvos (`formato="reais"` continua); a moeda entra só na hora de mostrar.
- **Leitura dentro da escrita:** no DuckDB, abrir `db.connect(read_only=True)` dentro de um `db.connect_write()` trava cerca de 15 s e termina em `RuntimeError`. Toda leitura de moeda acontece antes da escrita.
- **Commits:** um commit por tarefa (autorizado ao aprovar o plano), com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; nunca `git add -A`.
- **Revisor e mutação:** depois dos testes passarem, as Tasks 5 e 6 (lógica de portão, portfólio e risco) passam pelos agentes `revisor` e `mutacao`.
- **Ramo:** `cme-etapa3`, que saiu do `master`. Não muda código de estratégia, então não há re-assinatura de planos.

## Review Focus

1. Plano ativo de uma variante que muda de ativo depois de entrar no portfólio → as contas do portfólio recusam com a mensagem de moeda mista (Task 6).
2. Membro sem plano ativo (`wfa_id` nulo) → sem moeda, não bloqueia (Task 6).
3. Trocar o ativo `WIN$N` → MES → `WIN$N` → os rótulos da camada 4 voltam a "R$" (Task 3).
4. Valores negativo e zero em dólar → `-US$ 1,50` e `US$ 0,00` (Task 1).
5. Mineração do MES carregada com o seletor de ativo no WIN → mostra US$, porque segue o ativo da mineração (Task 4).

---

### Task 1: Formatação com moeda + referência de telas

**Files:**
- Modify: `core/ativo.py` (constantes), `ui/components/cartao.py:29-31`
- Create: `scripts/referencia_telas.py`, `tests/dados/telas_win/` (referência versionada)
- Test: `tests/test_moeda.py`, `tests/test_referencia_telas.py` (novos)

**Interfaces:**
- **Produces:**
  - `core.ativo.SIMBOLOS_MOEDA = {"BRL": "R$", "USD": "US$"}` e `core.ativo.NOMES_MOEDA = {"BRL": "reais", "USD": "dólares"}`;
  - `core.ativo.moeda_de(simbolo: str | None) -> str`: `ficha(simbolo).currency`, `"BRL"` se `None` ou sem YAML;
  - `cartao.simbolo_moeda(moeda) -> str` e `cartao.nome_moeda(moeda) -> str`, com `None` = BRL;
  - `cartao.dinheiro(v: float, moeda: str | None = "BRL") -> str`; `cartao.brl(v)` = `dinheiro(v, "BRL")`;
  - `scripts/referencia_telas.py gravar|conferir`, que grava e compara, para o WIN, a saída de cada função de tela listada nas Tasks 2–6.

- [ ] **Step 1: Referência antes de editar.** Escrever `scripts/referencia_telas.py`.
  - Com entradas fixas (as mesmas dos testes existentes de cada componente, ou um backtest curto do WIN no banco de teste), grava em `tests/dados/telas_win/*.json`:
    - `str(...)` de cada render de componente;
    - `fig.to_json()` de cada figura;
    - `portao_custo(...)["dica"]` e `portoes_rapidos(...)`;
    - `portfolio.correlacao/curvas/resumo/resumo_membros/simulacao_capital/simular_crescimento` e `_trades_para_risco` de um portfólio WIN de teste.
  - Lista de funções a cobrir:
    - `stats_cards.render/itens/cartoes`, `detalhes_cards.render`, `robustez_cards.render`;
    - as funções de `analytics_charts` chamadas em `ui/callbacks.py`, `results_grid.COLUNAS`;
    - `mine_porteira.painel`, `mine_regiao.cards`, `mine_charts.histograma/curva`, `scatter.figura`;
    - `wfa_panel.curva/kpis/selo/regiao_larga/fita/cards_mensais/mensal_fig`;
    - `candidata_panel.linhas/bloco_robustez/bloco_tamanho`, `ficha.ficha`;
    - as funções do `portfolio_panel`;
    - `metrics.format_panel`.
  - Rodar `gravar` **antes** de qualquer outra edição e commitar a referência.
  - `tests/test_referencia_telas.py` roda `conferir` e falha se algo diferir.
- [ ] **Step 2: Testes que falham** em `tests/test_moeda.py`:
  - `dinheiro(1234.5, "USD") == "US$ 1.234,50"`; `dinheiro(-57056, "USD") == "-US$ 57.056,00"`; `dinheiro(0, "USD") == "US$ 0,00"`; `dinheiro(-1.5, "USD") == "-US$ 1,50"`;
  - `dinheiro(1234.5) == brl(1234.5) == "R$ 1.234,50"`; `dinheiro(-3, None) == "-R$ 3,00"`;
  - `simbolo_moeda("USD") == "US$"`, `simbolo_moeda("EUR") == "EUR"`, `simbolo_moeda(None) == "R$"`; `nome_moeda("USD") == "dólares"`;
  - `moeda_de("WIN$N") == "BRL"`, `moeda_de("MES") == "USD"`, `moeda_de(None) == "BRL"`, `moeda_de("XYZ") == "BRL"`.
- [ ] **Step 3: Rodar** `pytest tests/test_moeda.py -q` → FAIL.
- [ ] **Step 4: Implementar.**
- [ ] **Step 5: Rodar** `pytest tests/test_moeda.py tests/test_referencia_telas.py -q` → PASS.
- [ ] **Step 6: Foto do motor** `scripts/foto_win.py gravar antes_etapa3`.
- [ ] **Step 7: Commit** `feat(cme): formatacao de dinheiro na moeda do ativo e referencia das telas do WIN`.

### Task 2: Backtest — resultado, Detalhes, Robustez, gráficos e lista de trades

**Files:**
- Modify:
  - `ui/components/stats_cards.py` (`cartoes` :31, `itens` :47, `render`; `brl` em :68, :73, :77, :107; dicas :94, :109, :110);
  - `ui/components/detalhes_cards.py` (11 `brl` e "em reais" :177);
  - `ui/components/robustez_cards.py` (17 `brl` e "em reais" :165);
  - `ui/components/analytics_charts.py` (:52-53, :71, :74, :90-91, :113, :147, :179, :190, :202, :204, :215, :243);
  - `ui/components/results_grid.py:44`;
  - `ui/callbacks.py`: `_detalhes` :235/254, `AC.*` :263, `_robustez` :269/283, o callback de rodar (:703, :736 e todos os seus `return`), e :2004-2017.
- Test: `tests/test_moeda_telas.py` (novo)

**Interfaces:**
- **Consumes:** `cartao.dinheiro/simbolo_moeda/nome_moeda`, `ativo.moeda_de` (Task 1).
- **Produces:**
  - `stats_cards.render(m, moeda="BRL")`, `stats_cards.itens(m, dicas=None, moeda="BRL")`, `stats_cards.cartoes(..., moeda="BRL")`;
  - `detalhes_cards.render(..., moeda="BRL")`, `robustez_cards.render(..., moeda="BRL")`;
  - cada função de `analytics_charts` chamada por `callbacks.py`, com `moeda="BRL"`;
  - `results_grid.colunas(moeda="BRL") -> list[dict]`, com `COLUNAS == colunas("BRL")`.

- [ ] **Step 1: Testes que falham** em `tests/test_moeda_telas.py`:
  - cada render e figura acima com `moeda="USD"` contém "US$" e "dólares" (onde havia "em reais"), e não contém "R$" nem "em reais";
  - `colunas("USD")` tem o cabeçalho `"líquido US$"`;
  - a igualdade com hoje é garantida pelo `test_referencia_telas.py`.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.** Em `callbacks.py`:
  - a moeda é `ativo_mod.moeda_de(run["simbolo"])`; em `_detalhes`, `getattr(f, "currency", "BRL")`;
  - no callback de rodar, `ativo_mod.moeda_de(simbolo)`;
  - a grade de trades ganha a saída `Output("grid-trades", "columnDefs")` no callback de rodar. É dono único, sem `allow_duplicate`. O módulo é `results_grid` (em `callbacks.py`, `RG` é `mine_regiao`). Todos os `return`, inclusive os de erro, levam o item a mais.
- [ ] **Step 4: Rodar** `pytest tests/test_moeda_telas.py tests/test_referencia_telas.py tests/test_telas_ativo.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(cme): backtest, Detalhes e Robustez na moeda do ativo`.

### Task 3: Rótulos fixos da camada 4

**Files:**
- Modify: `ui/components/controls.py:272-273, 293-294` (protegido; só estes 4 rótulos), `ui/callbacks.py`
- Test: `tests/test_moeda_rotulos.py` (novo)

**Interfaces:**
- **Consumes:** `ativo.moeda_de`, `cartao.simbolo_moeda` (Task 1).
- **Produces:**
  - spans `{"type": "moeda-c4", "i": "lim-ganho" | "lim-perda" | "risco" | "capital"}`, com texto inicial "R$";
  - a função de módulo `ui/callbacks.rotulos_moeda(ativo: str | None, n: int) -> list[str]`;
  - um callback fino com `Output({"type": "moeda-c4", "i": ALL}, "children")` e `Input("ativo", "value")`, que devolve `rotulos_moeda(ativo, len(ctx.outputs_list))`, com `prevent_initial_call=True` (o app abre em `WIN$N` e o layout já diz "R$").

- [ ] **Step 1: Testes que falham:**
  - o texto visível dos 4 rótulos no layout é exatamente o de hoje ("ganho máx. R$/contrato", "perda máx. R$/contrato", "risco/trade R$", "capital inicial R$");
  - o layout tem exatamente 4 spans `moeda-c4`;
  - `rotulos_moeda("MES", 4) == ["US$"] * 4`; `rotulos_moeda("WIN$N", 4) == ["R$"] * 4`; `rotulos_moeda(None, 4) == ["R$"] * 4`.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.** O rótulo vira uma lista de filhos, por exemplo `["ganho máx. ", html.Span("R$", id={"type": "moeda-c4", "i": "lim-ganho"}), "/contrato"]`.
- [ ] **Step 4: Rodar** `pytest tests/test_moeda_rotulos.py tests/test_perfil_por_ativo.py tests/test_referencia_telas.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(cme): rotulos de dinheiro da camada 4 seguem o ativo` (no corpo: "controls.py alterado no minimo (D11)").

### Task 4: Mineração

**Files:**
- Modify:
  - `core/optimizer.py` (`MINERACAO.rodar` ~:295/:444, para guardar o símbolo no estado);
  - `ui/components/mine_porteira.py` (:34, :51-53, :167, :175, :176, :191 "em reais", :200, :210, :279);
  - `ui/components/mine_regiao.py` (:32, :40, :50, :51, :57);
  - `ui/components/mine_charts.py:23`, `ui/components/scatter.py:102-103`;
  - `ui/callbacks.py`: :1040 (carregar mineração salva), `desenhar_scatter` :1127-1136, `distribuicao_mine` :1180-1213, `porteira_mine` :1219-1234.
- Test: `tests/test_moeda_mineracao.py` (novo)

**Interfaces:**
- **Consumes:** Task 1.
- **Produces:**
  - `MINERACAO.estado["symbol"]`, gravado ao rodar e ao carregar uma salva (de `optimizer.detalhes_salva(run_id)["symbol"]`);
  - `mine_porteira.painel(av, truncada, moeda="BRL")`, `mine_regiao.cards(..., moeda="BRL")`, `scatter.figura(..., moeda="BRL")`;
  - `mine_charts.histograma/curva(..., moeda: str | None)`: o bool de hoje vira código ou `None`. `None` é métrica que não é dinheiro; o chamador passa `moeda if metrica in MS.DINHEIRO else None`. Para os chamadores que passavam `True`, `True` passa a valer `"BRL"`.
  - Os três callbacks leem a moeda com `ativo_mod.moeda_de(MINERACAO.estado.get("symbol"))`, e não pelo seletor de ativo.

- [ ] **Step 1: Testes que falham:**
  - com USD aparece "US$" e não "R$";
  - `mine_charts` com `moeda=None` não tem prefixo de dinheiro;
  - depois de carregar uma mineração salva com símbolo "MES", `MINERACAO.estado["symbol"] == "MES"`.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `pytest tests/test_moeda_mineracao.py tests/test_referencia_telas.py tests/ -q -k "mine or scatter or mineracao or optimizer or referencia"` → PASS.
- [ ] **Step 5: Commit** `feat(cme): mineracao na moeda do ativo`.

### Task 5: Walk-Forward, Candidata e Ficha da estratégia

**Files:**
- Modify:
  - `ui/components/wfa_panel.py`:
    - `DICAS_OOS` :254-296, que vira a função `dicas_oos(moeda)`; `DICAS_OOS = dicas_oos("BRL")` continua existindo;
    - `curva` :167/:189/:215/:230/:232/:234, `kpis` :324/:360, `_fmt_portao` :805/:837, `_linha_portao` :845;
    - `selo`, `regiao_larga` :906, `fita` :1091, `mensal_fig` :1126/:1132, `cards_mensais` :1150-1157;
  - `ui/components/candidata_panel.py` (`linhas` :118, :96, :97, :137, :169, :197, "em reais" :86/:327/:406, rótulo :568);
  - `core/candidata.py` (`portao_custo` :533-547, `portoes_rapidos` :821);
  - `ui/components/ficha.py:54-59, 166`;
  - `ui/callbacks.py` :1562-1580, :1965;
  - `ui/callbacks_candidata.py` :170, :405, :411, `cand_tamanho` :414-444.
- Test: `tests/test_moeda_wfa_candidata.py` (novo)

**Interfaces:**
- **Consumes:** Task 1, e `stats_cards.itens/cartoes(..., moeda)` da Task 2.
- **Produces:**
  - `wfa_panel.curva/kpis/selo/regiao_larga/fita/cards_mensais/mensal_fig(..., moeda="BRL")`, `_fmt_portao(p, moeda="BRL")`, `_linha_portao(p, moeda="BRL")`;
  - `candidata_panel.linhas/bloco_robustez/bloco_tamanho(..., moeda="BRL")`;
  - `ficha.ficha(..., moeda="BRL")`, só nomeado, com o mesmo padrão para o ao vivo;
  - `core.candidata.portao_custo(lucro_liquido, contratos, tick_value, simbolo: str | None = None)` e `portoes_rapidos(..., simbolo=None)`. A frase "No mini índice 1 tick vale mais que a corretagem inteira, e ordem a mercado na hora da pressa costuma escorregar isso." **só sai** quando `ativo.moeda_de(simbolo) != "BRL"`. Com `None` ou BRL, o texto é o de hoje;
  - o span `{"type": "moeda-cand", "i": "margem"}` no rótulo "garantia por contrato (R$)", atualizado por uma saída a mais em `cand_tamanho`, que já tem `d["symbol"]`.

- [ ] **Step 1: Testes que falham:**
  - com USD, cada função acima mostra "US$" e "dólares";
  - `portao_custo(..., simbolo="MES")["dica"]` não contém "mini índice";
  - `portao_custo(..., simbolo="WIN$N")["dica"]` é igual à de `simbolo=None` (texto de hoje);
  - `portoes_rapidos(..., simbolo="MES")` repassa o símbolo ao portão de custo;
  - `cand_tamanho` com uma Candidata do MES devolve "US$" no span da margem.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `pytest tests/test_moeda_wfa_candidata.py tests/test_referencia_telas.py tests/test_candidata.py tests/test_wfa_panel_selo.py -q` → PASS.
- [ ] **Step 5: Revisor e mutação** (agentes `revisor` e `mutacao`) sobre `portao_custo`/`portoes_rapidos`.
- [ ] **Step 6: Commit** `feat(cme): Walk-Forward, Candidata e ficha na moeda do ativo`.

### Task 6: Portfólio — bloqueio de moeda mista e valores na moeda

**Files:**
- Modify:
  - `core/portfolio.py`: `adicionar_variante` :67-87, `membros` :120, `_trades_para_risco` :193-213, `correlacao` :158, `curvas` :300, `resumo` :366, `resumo_membros` :389, `simulacao_capital` :421, `simular_crescimento` :530;
  - `ui/components/portfolio_panel.py`: os "R$" do mapa, `tickprefix` :442/:487;
  - `ui/callbacks_portfolio.py`: `_parse_capital` :14-29, `abrir_detalhe` :84-175 (inclusive o `return` de `pid is None` em :109-112), `simular_crescimento` :191-215.
- Test: `tests/test_portfolio_moeda.py` (novo)

**Interfaces:**
- **Consumes:** Task 1.
- **Produces:**
  - `portfolio.MoedaMista(Exception)`, **não** `ValueError`, para não ser engolida pelos `except ValueError` existentes;
    - mensagem: "O portfólio mistura R$ e US$: variantes de moedas diferentes não podem ficar no mesmo portfólio.", com os símbolos das moedas presentes em ordem alfabética do código;
  - `portfolio.moeda(portfolio_id) -> str | None`: a moeda dos membros com `wfa_id`, via `wfa_runs.symbol` → `ativo.moeda_de`; `None` se nenhum tem; levanta `MoedaMista` se houver mais de uma;
  - `membros()` passa a trazer `"symbol"` (`None` sem plano);
  - as funções do `portfolio_panel` ganham `moeda="BRL"`.

- [ ] **Step 1: Testes que falham** (banco de teste do `conftest`):
  - **ao adicionar:**
    - WIN e MES no mesmo portfólio → o `adicionar_variante` da segunda levanta `MoedaMista` e não grava;
    - MES + MNQ → aceita, e `moeda()` dá `"USD"`;
    - membro sem plano → não bloqueia;
    - o `adicionar_variante` de uma variante WIN continua rápido: o teste mede menos de 2 s, sem a trava de leitura dentro da escrita;
  - **plano ativo que muda de ativo depois de entrar:** a variante entra com plano WIN e o plano ativo vira MES → `correlacao`, `curvas`, `resumo`, `resumo_membros`, `simulacao_capital` e `simular_crescimento` levantam `MoedaMista`;
  - **risco:** com `db.upsert_instrument(con, load_instrument_yaml("MES"))` gravado, `_trades_para_risco` de um WFA do MES com `mae=1000` e 1 contrato dá `mae_reais == 50.0`; sem linha em `instruments`, o padrão continua 1.0 (os testes de `tests/test_portfolio.py:176-239` passam sem mudança);
  - **capital digitado** (formato brasileiro: ponto = milhar, vírgula = decimal; decisão do usuário em 29/10 de corrigir o defeito antigo "10.000" → 10):
    - `_parse_capital("10.000") == 10000.0`, `_parse_capital("R$ 10.000") == 10000.0`, `_parse_capital("US$ 10000") == 10000.0`, `_parse_capital("US$ 10.000,00") == 10000.0`;
    - `_parse_capital("1.234.567,8") == 1234567.8`, `_parse_capital("2500,50") == 2500.5`;
    - inválidos continuam `None`;
    - os testes antigos que dependiam de "10.000" → 10 são corrigidos, com nota no relatório;
  - **callbacks:**
    - `abrir_detalhe` com uma adição recusada mostra a mensagem em `pf-avisos` e desenha o portfólio sem o membro;
    - `simular_crescimento` com portfólio misto mostra a mensagem de moeda, não a de "precisam ser números positivos";
  - **tela:** os renders do painel com `moeda="USD"` mostram "US$".
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.**
  - **`adicionar_variante`:** a moeda da variante nova e a dos membros são lidas **antes** do `db.connect_write()`, numa leitura própria.
  - **`_trades_para_risco`:** continua lendo do banco, com `SELECT point_value, price_decimals FROM instruments`, e faz `ponto = point_value / 10**price_decimals`, com o mesmo padrão 1.0.
  - **`callbacks_portfolio`:** `except P.MoedaMista as e` antes de qualquer `except ValueError`. Os placeholders "capital do portfólio (R$)" e "capital inicial (R$)" (:44, :92) viram saídas `Output("pf-capital", "placeholder")` e `Output("pf-cresc-capital", "placeholder")` do `abrir_detalhe`, em todos os seus `return`.
  - **Portfólio 6:** está na conta real, é todo `WIN$N`, e nada do caminho ao vivo chama `moeda()` nem as contas alteradas. `callbacks_ao_vivo` só usa `P.listar`.
- [ ] **Step 4: Rodar** `pytest tests/test_portfolio_moeda.py tests/test_portfolio.py tests/test_referencia_telas.py tests/ -q -k "portfolio or referencia or captura or ao_vivo"` → PASS.
- [ ] **Step 5: Revisor e mutação** sobre `moeda`, `adicionar_variante` e `_trades_para_risco`.
- [ ] **Step 6: Commit** `feat(cme): portfolio recusa moedas misturadas e mostra a moeda`.

### Task 7: Linha de comando e conferência final

**Files:**
- Modify: `core/metrics.py:250` (`format_panel`), `backtest.py:60-61` (help)
- Test: `tests/test_moeda.py` (acrescentar)

**Interfaces:**
- **Consumes:** `core.ativo.SIMBOLOS_MOEDA` (Task 1). O core não importa `ui`.
- **Produces:** `metrics.format_panel(m, moeda="BRL")`, com o alinhamento próprio de hoje e só o símbolo trocado. `backtest.py` passa `res.instrument.get("currency", "BRL")`.

- [ ] **Step 1: Teste que falha:** `format_panel(m, "USD")` contém "US$" e não "R$".
- [ ] **Step 2: Implementar.** O help do `--lim-ganho`/`--lim-perda` passa a dizer "na moeda do ativo, por contrato".
- [ ] **Step 3: Suíte inteira** em segundo plano: `pytest -q` → todos passam.
- [ ] **Step 4: Conferências:**
  - `scripts/referencia_telas.py conferir` → idêntica;
  - `scripts/foto_win.py conferir antes_etapa3` → idêntica.
- [ ] **Step 5: Conferência no app** (preview servindo este ramo):
  - no `WIN$N`, tudo com "R$", como antes;
  - no MES, "US$" no resultado, nos Detalhes, na Robustez, na lista de trades, nos rótulos da camada 4, no WFA e na Candidata;
  - trocar MES → `WIN$N` e ver os rótulos voltarem a "R$".
- [ ] **Step 6: Commit** `feat(cme): linha de comando na moeda do ativo`. Atualizar a seção de estado da spec para "depois da etapa 3", registrando:
  - os textos fixos que ficaram em R$;
  - o desvio da spec no portão de custo (frase retirada fora do WIN, em vez de "descrição do ativo");
  - commit `docs(spec): ativos da CME - estado depois da etapa 3`.
