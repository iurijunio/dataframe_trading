# Ativos da CME — etapa 4 (faixas por ativo, opção B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ao escolher MES ou MNQ, a tela já mostra valores e faixas de mineração do tamanho do ativo: nos parâmetros em pontos das estratégias e no stop, alvo e trailing da camada 4. As faixas continuam editáveis, e o WIN não muda.

**Architecture:**
- Opção B, aprovada pelo usuário em 30/10/2026, no lugar da seção 6 da spec ("schema efetivo" no motor).
- As faixas ficam na ficha de cada micro (`faixas:` no YAML) e só preenchem a tela. O motor, a mineração, o Walk-Forward, a Candidata e a validação **não mudam**.
- A tela lê as faixas por `core/ativo.py`:
  - os parâmetros da estratégia são montados com elas, pelo callback que já é dono da seção (`estrategia_ou_mineracao`);
  - os campos de stop, alvo e trailing da camada 4 são preenchidos pelo callback que já aplica o perfil do ativo (`aplicar_perfil_do_ativo`).

**Tech Stack:** Python, Dash 4.4.1, YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-ativos-cme-design.md` (seções 6 e 7, e "Estado depois da etapa 3"). Desvio aprovado: opção B.

## Global Constraints

- **Tabela aprovada pelo usuário em 30/10/2026** (copiar exatamente; valor · de–até · passo, em pontos inteiros):

  | Campo | Chave | MES | MNQ |
  |---|---|---|---|
  | Stop | `stop_pontos` | 8 · 3–16 · 1 | 45 · 15–90 · 5 |
  | Alvo | `alvo_pontos` | 16 · 6–32 · 2 | 90 · 30–180 · 10 |
  | Trailing | `trailing_pontos` | 0 · 0–14 · 2 | 0 · 0–80 · 10 |
  | `rompimento_abertura` | `filtro_amplitude` | 0 · 0–40 · 2 | 0 · 0–220 · 10 |
  | `rompimento_canal` | `filtro_amplitude` | 0 · 0–80 · 2 | 0 · 0–460 · 10 |
  | `rompimento_ema_abertura` | `distancia_abertura` | 0 · 0–80 · 2 | 0 · 0–400 · 10 |
  | `adx_direcao` | `amplitude_max` | 25 · 5–80 · 5 | 150 · 25–450 · 25 |

- **Fonte única do stop e do alvo padrão:** `perfil_padrao.stop_pontos`/`alvo_pontos` passam a MES 8/16 e MNQ 45/90. Eram 10/20 e 40/80 provisórios; o comentário "PROVISORIOS" sai dos YAMLs. Um teste garante que eles são iguais ao `valor` de `faixas.comum`.
- **WIN idêntico:** `win.yaml` não ganha `faixas`. Com o WIN, a tela monta exatamente o mesmo de hoje. A prova é a **referência de telas ampliada na Task 1**, antes de qualquer mudança:
  - `campos_da_estrategia` de todas as estratégias registradas;
  - o layout da camada 4 (`execucao()` ou equivalente).

  Nunca regravar a referência a partir do código novo.
- **Fora do escopo:** motor, `core/optimizer.py`, `strategies/*.py`, validação, mineração, Walk-Forward, Candidata e caminho ao vivo não mudam. Não há re-assinatura de planos.
- **Arquivo protegido `ui/components/controls.py`:** autorizado pelo usuário em 30/10/2026, mudança mínima. Só:
  - `campos_da_estrategia`;
  - os três `_opt` de stop, alvo e trailing em pontos, que passam a ler de uma constante de padrões.
- **Atributo `step`** (Dash 4.4.1: um valor digitado fora do passo vira `None`):
  - nos micros, todo campo que tem faixa do ativo usa `step=1`, por causa dos pontos inteiros da decisão C1;
  - o passo da mineração fica só na célula "passo";
  - no WIN, o `step` de hoje.
- **Prioridade das faixas, chave por chave** (`valor`, `de`, `passo`, `ate`): mineração carregada > faixa do ativo > schema ou padrão da camada 4.
- **Ativo de referência:**
  - ao carregar uma mineração salva, as faixas de reserva vêm do ativo **da mineração** (`d["symbol"]`), não do seletor;
  - nos demais casos, do seletor.
- **Trocar o ativo** reconstrói a seção de parâmetros com as faixas do novo ativo **só quando não há mineração rodando nem carregada**. Com mineração rodando ou carregada, a seção fica como está e a mineração não é interrompida. Nunca chamar `MINERACAO.esquecer()`/`parar()` por causa do ativo.
- **Símbolo sem YAML ou ficha sem `faixas`:** se comporta como o WIN (`{}`), sem erro. `faixas_do_ativo` devolve cópias, nunca o dict do cache.
- **Símbolo do WIN é `"WIN$N"`.**
- **Para conferir no app**, reabrir o `iniciar.bat` (as fichas ficam em cache).
- **Commits:** com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; nunca `git add -A`.

## Review Focus

1. Trocar MES → `WIN$N` → os campos de stop, alvo e trailing e os parâmetros voltam aos valores e faixas de hoje (Tasks 2 e 3).
2. Mineração do WIN carregada e o seletor trocado para o MES → a seção não muda e a mineração continua carregada. Mineração rodando → não é interrompida (Task 2).
3. Usuário digita alvo 17 no MES → o campo aceita (`step=1`) (Tasks 2 e 3).
4. Estratégia sem faixas no YAML (ex.: `cruzamento`) no MES → campos iguais aos de hoje (Task 2).
5. Mineração salva do MES carregada com o seletor no WIN → um parâmetro não minerado mostra a faixa do MES, não a do WIN (Task 2).

---

### Task 1: Referência ampliada, faixas na ficha e leitura em `core/ativo.py`

**Files:**
- Modify: `scripts/referencia_telas.py` (+ JSON novo em `tests/dados/telas_win/`), `configs/instruments/mes.yaml`, `configs/instruments/mnq.yaml`, `core/ativo.py`
- Test: `tests/test_faixas_ativo.py` (novo)

**Interfaces:**
- **Produces:**
  - O bloco YAML `faixas:`, com `comum:` (`stop_pontos`, `alvo_pontos`, `trailing_pontos`) e uma chave por estratégia, com o nome do registro (`rompimento_abertura`, `rompimento_canal`, `rompimento_ema_abertura`, `adx_direcao`). Cada item é `{valor, de, passo, ate}`.
  - `Ficha.faixas: dict | None` (`hash=False, compare=False`).
  - `core.ativo.faixas_do_ativo(simbolo: str | None, estrategia: str | None = None) -> dict[str, dict]`: a junção (cópia) de `comum` com o bloco da estratégia. Dá `{}` sem faixas, com símbolo `None` ou sem YAML.

- [ ] **Step 1: Ampliar a referência ANTES de qualquer outra mudança.**
  - Acrescentar a `scripts/referencia_telas.py`:
    - `campos_da_estrategia(mod)` de cada estratégia do registro;
    - `campos_da_estrategia(mod, faixas)` com uma faixa de mineração sintética;
    - o layout da camada 4 que contém os `_opt` de stop, alvo e trailing.
  - Tudo serializado pelo `_c()` canônico que já existe.
  - Rodar `gravar` e conferir que as entradas antigas não mudaram (`git diff --stat tests/dados/telas_win` mostra só arquivos novos ou entradas novas).
  - Commit `test(cme): referencia de telas cobre parametros e camada 4`.
- [ ] **Step 2: Testes que falham** em `tests/test_faixas_ativo.py`:
  - **teste parametrizado com as 14 linhas da tabela**, por exemplo `faixas_do_ativo("MES", "rompimento_canal")["filtro_amplitude"] == {"valor": 0, "de": 0, "passo": 2, "ate": 80}` e `faixas_do_ativo("MNQ")["stop_pontos"] == {"valor": 45, "de": 15, "passo": 5, "ate": 90}`;
  - **sem faixas:** `faixas_do_ativo("WIN$N", "rompimento_canal") == {}`; `faixas_do_ativo(None) == {}`; `faixas_do_ativo("XYZ") == {}`;
  - **cópia:** mexer no dict devolvido não altera uma segunda chamada;
  - **chaves válidas:** toda estratégia em `faixas` existe no registro, e cada parâmetro existe no `params_schema` dela, com `valor`, `de` e `ate` dentro de `min`/`max`;
  - **perfil:** `perfil_padrao` do MES dá stop 8 e alvo 16; o do MNQ, 45 e 90; e é igual ao `valor` de `faixas.comum`.
- [ ] **Step 3: Rodar** `pytest tests/test_faixas_ativo.py -q` → FAIL.
- [ ] **Step 4: Implementar.**
  - **YAMLs:** comentário dizendo que são as faixas aprovadas em 30/10/2026 e que só preenchem a tela. Remover "PROVISORIOS".
  - **`faixas_do_ativo`:** tratar `FileNotFoundError`.
- [ ] **Step 5: Rodar** `pytest tests/test_faixas_ativo.py tests/test_ativo.py tests/test_perfil_por_ativo.py tests/test_referencia_telas.py -q` → PASS. Se algum teste antigo esperar 10/20 ou 40/80, atualizar e anotar no relatório.
- [ ] **Step 6: Commit** `feat(cme): faixas de mineracao do MES e do MNQ na ficha`.

### Task 2: Parâmetros da estratégia com as faixas do ativo

**Files:**
- Modify: `ui/components/controls.py` (`campos_da_estrategia` :128-149), `ui/callbacks.py` (`estrategia_ou_mineracao` :462-504, `_trocar_estrategia` :506-519, `_carregar_mineracao` :521-574)
- Test: `tests/test_faixas_tela.py` (novo)

**Interfaces:**
- **Consumes:** `ativo.faixas_do_ativo(simbolo, estrategia)` (Task 1).
- **Produces:** `controls.campos_da_estrategia(mod=None, faixas: dict | None = None, faixas_ativo: dict | None = None)`.
  - **Prioridade:** chave por chave, `faixas` > `faixas_ativo` > schema/`_ate_padrao`.
  - **`step`:** 1 quando o parâmetro tem faixa do ativo; senão `meta["step"]`.
  - **`valor` None:** cai na faixa do ativo ou no default antes de `_ate_padrao`, sem TypeError.
  - **Sem faixa do ativo:** com `faixas_ativo` vazio ou `None`, a saída é idêntica à de hoje.

- [ ] **Step 1: Testes que falham** (chamando `_trocar_estrategia` e `_carregar_mineracao` diretamente; se forem internas a `register`, extrair para funções de módulo testáveis, sem mudar o comportamento):
  - **canal no MES:** `campos_da_estrategia(mod_canal, None, faixas_do_ativo("MES", "rompimento_canal"))` dá `filtro_amplitude` com valor 0, de 0, passo 2, até 80, e `step` 1 nos inputs de valor, de e até;
  - **mineração na frente:** uma mineração com `filtro_amplitude` `{"valor": 100, "de": 50, "passo": 50, "ate": 300, "on": True}` vence a faixa do ativo;
  - **chave por chave:** uma faixa de mineração só com `{"valor": 4}` leva o resto (de, passo, até) da faixa do ativo;
  - **ADX:** `adx_direcao` no MES dá `amplitude_max` 25 · 5–80 · 5;
  - **`cruzamento` no MES:** igual a hoje;
  - **troca de estratégia:** `_trocar_estrategia(nome, r, simbolo="MES")` usa as faixas do MES; com `"WIN$N"`, a seção é idêntica à referência;
  - **troca de ativo:**
    - sem mineração rodando nem carregada, reconstrói a seção;
    - com `MINERACAO` rodando ou com tabela carregada, devolve `no_update` para a seção e **não** chama `esquecer`/`parar` (testar com um duplo ou espião);
  - **mineração do MES com o seletor no WIN:** `_carregar_mineracao` usa as faixas do MES (de `d["symbol"]`) para o parâmetro que a mineração não tem.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.**
  - Acrescentar `Input("ativo", "value")` ao `estrategia_ou_mineracao`, que continua o único dono de `params-body` (ler o docstring dele), e `State("ativo", "value")` para a troca de estratégia.
  - Usar o `nome` da estratégia, não `registry.atual()`.
- [ ] **Step 4: Rodar** `pytest tests/test_faixas_tela.py tests/test_referencia_telas.py tests/test_callbacks_sem_ciclo.py -q` e os testes existentes de mineração e estratégia (`pytest tests/ -q -k "mineracao or estrategia or controls"`) → PASS.
- [ ] **Step 5: Commit** `feat(cme): parametros da estrategia com as faixas do ativo` (no corpo: "controls.py alterado no minimo, autorizado em 30/10").

### Task 3: Stop, alvo e trailing da camada 4 seguem o ativo

**Files:**
- Modify: `ui/components/controls.py` (os `_opt` de `alvo_pontos` :233, `stop_pontos` :250 e `trailing_pontos` :267), `ui/callbacks.py` (`aplicar_perfil_do_ativo` :577-595)
- Test: `tests/test_faixas_tela.py` (acrescentar)

**Interfaces:**
- **Consumes:** Task 1.
- **Produces:**
  - a constante `controls.PADRAO_C4 = {"alvo_pontos": (600, 200, 100, 1200, 10), "stop_pontos": (300, 100, 50, 600, 10), "trailing_pontos": (0, 0, 50, 500, 10)}`, com (valor, de, passo, até, step) iguais aos literais de hoje. Os três `_opt` passam a ler dela, e o layout continua idêntico (referência da Task 1);
  - `aplicar_perfil_do_ativo` estendido. É o único callback da camada 4 disparado pelo ativo, e para cada X em stop, alvo e trailing ele escreve:
    - `value` de `{"type": "val", "p": X}` e das três células `{"type": "opt", "p": X, "k": "de"|"passo"|"ate"}`, com `allow_duplicate=True` (já há saídas ALL desses tipos em `estrategia_ou_mineracao`);
    - `step` do val e das células "de"/"até": 1 no micro, o step de `PADRAO_C4` no WIN.

    Os valores vêm de `faixas_do_ativo(simbolo)` ou, sem faixa (WIN), de `PADRAO_C4`. Hoje o WIN devolve `no_update`; a partir daqui, devolve `PADRAO_C4` para os três campos, para a volta do MES funcionar.
  - Com mineração carregada ou rodando, os três campos também ficam como estão (`no_update`), pela mesma regra da Task 2.

- [ ] **Step 1: Testes que falham** (com a lógica numa função de módulo testável):
  - com "MES": stop 8 · 3–16 · 1, alvo 16 · 6–32 · 2, trailing 0 · 0–14 · 2, todos com `step` 1;
  - com "MNQ": os valores da tabela;
  - com "WIN$N": exatamente `PADRAO_C4`, para cobrir a volta do MES;
  - com mineração carregada: os três campos ficam com `no_update`;
  - **saídas sem conflito:** entre os callbacks que têm `Input("ativo")`, nenhum par de saídas tem o mesmo id e a mesma propriedade, contando ALL contra ids específicos; toda saída que coincide com uma ALL de outro callback tem `allow_duplicate`.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `pytest tests/test_faixas_tela.py tests/test_perfil_por_ativo.py tests/test_moeda_rotulos.py tests/test_referencia_telas.py tests/test_callbacks_sem_ciclo.py -q`, e depois a suíte inteira → PASS.
- [ ] **Step 5: Commit** `feat(cme): stop, alvo e trailing da camada 4 seguem o ativo`.
- [ ] **Step 6: Conferência no app** (controlador, numa cópia separada). Conferir:
  - no MES, os parâmetros do rompimento de canal e a camada 4 mostram a tabela, digitar 17 no alvo é aceito, e uma mineração curta roda;
  - na volta ao WIN, tudo como hoje;
  - o console do navegador sem "Overlapping wildcard callback outputs";
  - atualizar a spec (seção de estado) e o "Estado depois da etapa 3" (:455, os provisórios).
