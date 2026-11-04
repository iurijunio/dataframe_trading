# Busca automática por nichos — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development
> (recomendado) ou superpowers:executing-plans, tarefa por tarefa. Passos com
> caixa (`- [ ]`) para acompanhar.

**Objetivo:** uma subtela "Busca automática" na Mineração que, num processo à
parte, testa milhares de combinações de UMA estratégia (pyribs/MAP-Elites) e
entrega um mapa de nichos bons e diferentes entre si, com detalhe e o atalho
"Minerar a região".

**Arquitetura:** o motor ganha duas camadas (`preparar` = sinal, caro, uma vez
por tempo gráfico + parâmetros essenciais; `executar` = janela, dias, direção,
stop e alvo, barato, muitas vezes), com resultado idêntico ao de hoje. A busca
(`core/busca/`) lê um catálogo declarativo, codifica cada combinação como um
vetor para a pyribs, avalia em lotes num pool de processos com a MESMA conta da
Varredura (`wf.avaliar`) e grava num banco próprio, `data/buscas.duckdb`. O app
só manda comandos (arquivo `controle.json`) e lê o andamento (`estado.json` +
leitura do banco). Agrupamento e detalhe são contas puras sobre o banco da
busca; a tela é o layout B.

**Tecnologia:** Python 3.13, NumPy 2.5, Numba, DuckDB 1.5, Dash, `ribs==0.12.0`.

**Desenho:** `docs/superpowers/specs/2026-11-03-busca-automatica-design.md`
**Contrato visual:** `docs/superpowers/specs/2026-11-03-busca-automatica/layout-b.html`

## Restrições globais

- Protótipo é contrato: qualquer desvio visual ou de texto, perguntar antes.
- Nada de texto explicativo visível; explicação só no "(?)". Títulos curtos.
- Código, nomes, comentários e textos em português; comentário diz o porquê.
- `core/` não importa Dash. Nenhum teste toca `data/` (nem `database.duckdb`
  nem `buscas.duckdb`): o `tests/conftest.py` autouse desvia os dois.
- Nunca editar/stagear `ui/components/controls.py`, `ui/components/wfa_matriz.py`,
  `strategies/rompimento_abertura.py`. **Nenhum arquivo de `strategies/` é
  editado** neste plano: mudar uma estratégia muda o `codigo_hash` e o plano #6
  (conta REAL) passaria a acusar "código mudou".
- Resultado de cada combinação = o da Varredura de hoje (mesmos folds,
  `wf.avaliar`, mesmo `score`), bit a bit.
- Foto do WIN obrigatória antes e depois de mexer no motor
  (`scripts/foto_win.py gravar|conferir`): idêntico.
- Mínimo de trades padrão **400**; critério padrão **fator de recuperação**.
- Núcleos 1 a `os.cpu_count()`; padrão **20** com "Parar às" ligado, **4**
  desligado. "Parar às" padrão **08:30**, ligado.
- Nada volta sozinho: sem tarefa agendada, sem arranque pelo `iniciar.bat`.
- Uma cópia do app (preview) só fora do pregão (09:00–18:30 dias úteis) e com
  o app real fechado — ela abre o banco real.
- Nos worktrees `data/` e `.venv/` são junções: crie com `cmd /c mklink /J`,
  remova com `cmd /c rmdir`, nunca `rm -rf`.
- Commits: arquivos pelo caminho (nunca `git add -A`), mensagem num arquivo do
  scratchpad e `git commit -F`, com o trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Mudança de impacto: teste falhando → código → teste passando → agente
  `mutacao` → agente `revisor` (fundo) → suíte inteira (em segundo plano) →
  tela contra o banco real → commit. **Antes de juntar cada etapa no `master`,
  o ok do usuário.**

## Foco de revisão

1. **Busca rodando no pregão** (captura e Ordens real abertas): a busca nunca
   abre `database.duckdb` (só o Parquet), roda com prioridade abaixo do normal
   e nunca segura `buscas.duckdb` aberto entre lotes. Teste: `test_busca_processo.py::test_nao_abre_banco_principal`.
2. **PC desligou / processo morreu no meio:** estado "Interrompida", o que foi
   gravado fica, Continuar retoma do último lote salvo sem repetir nem perder
   combinações. Teste: `test_busca_motor.py::test_retomar_apos_queda`.
3. **Combinação sem trade, com FR infinito (sem perda) ou abaixo do mínimo:**
   nunca vira campeã nem membro; casa fica listrada; mapa e cor não quebram com
   `inf`. Testes em `test_busca_avaliador.py` e `test_busca_projecao.py`.
4. **Ativo da CME:** janela da busca em hora de NY, respeitando
   `janela_valida` (não atravessa a pausa); faixas de stop/alvo de
   `faixas_do_ativo`; moeda do ativo no detalhe. Testes em
   `test_busca_catalogo.py::test_mes_*`.
5. **App e busca disputando `buscas.duckdb`:** leitura do app com o processo
   gravando não trava nem quebra a tela (usa a última leitura). Teste:
   `test_busca_banco.py::test_leitura_com_escritor_ocupado`.

---

# Etapa 1 — Motor em camadas

## Tarefa 0: worktree pronto

- [ ] **Passo 1:** criar as junções (se faltarem):
  `cmd /c mklink /J data ..\..\..\data` e `cmd /c mklink /J .venv ..\..\..\.venv`
  na raiz do worktree. Conferir `.venv/Scripts/python.exe -m pytest -q` verde
  (2.776) em segundo plano.

## Tarefa 1: gabarito do motor antes de mexer

**Arquivos:**
- Criar: `scripts/gabarito_motor.py`, `tests/dados/motor_camadas.json`
- Teste: `tests/test_motor_camadas.py`

- [ ] **Passo 1: foto do WIN antes.** Fora do pregão:
  `.venv/Scripts/python.exe scripts/foto_win.py gravar antes-camadas`.
- [ ] **Passo 2: gerar o gabarito com o código ANTIGO.** `scripts/gabarito_motor.py
  gravar` roda `run_strategy` para cada estratégia de `registry.descobrir()` ×
  cada perfil de `PERFIS_GABARITO` (abaixo), em WIN$N 2024-01-01..2024-06-30 e
  MES 2024-01-01..2024-06-30 (Parquet), e grava em `tests/dados/motor_camadas.json`
  `{chave: sha256}` do conjunto `(entry_i, exit_i, side, entry_px, exit_px,
  reason, points)` + `n_trades`. Recusa sobrescrever o arquivo (como o
  `campos_menu.json`: **nunca regravar**).
  `PERFIS_GABARITO` cobre, um por linha: padrão; stop ATR + alvo
  multiplicador; stop % + alvo %; alvo ATR; janela 10:00–11:30 só ter/qui;
  direção compra; direção venda; ADX tendência com DI e subindo; ADX rango;
  sem_entrada 12:00; limites diários (ganho, perda, máx. trades, máx.
  prejuízos); breakeven + stop móvel + trailing; timeframes M1, M5, M15; e,
  por estratégia, "virar a mão" (`saida` = 2) e `vela_aberta=True`.
  **Feito em 03/11:** 142 casos gravados com o motor antigo.
- [ ] **Passo 3: teste que confere o gabarito.**

```python
def test_motor_bate_com_o_gabarito(gabarito, casos):
    for chave, (bars, mod, params, perfil, inst) in casos:
        res = run_strategy(bars, mod, params, perfil, inst)
        assert assinatura(res) == gabarito[chave], chave
```
  (`assinatura` mora em `scripts/gabarito_motor.py`; o teste pula se o Parquet
  do ativo não existir.)
- [ ] **Passo 4:** rodar → PASSA (é o código de hoje). Commit:
  `test(motor): gabarito dos trades antes das camadas`.

## Tarefa 2: `preparar` e `executar`

**Arquivos:**
- Modificar: `core/engine/execution.py` (`run_strategy`, `backtest`)
- Teste: `tests/test_motor_camadas.py`

**Interfaces (produz):**
- `@dataclass Preparado`: `timeframe: str`, `bars: dict` (M1), `sinais: Signals`
  (já no índice M1), `bars_tf: dict`, `fechada: np.ndarray`, `inst_m: dict`,
  `ficha: Ficha | None`, `cache: dict` (vazio ao nascer).
- `preparar(bars, estrategia, params, timeframe: str, instrument: dict,
  vela_aberta: bool = False) -> Preparado` — tudo o que hoje vem antes de
  `backtest(...)` em `run_strategy`. (O horário de referência da abertura NÃO
  entra na busca — decisão do usuário em 03/11: a janela de entradas já cobre
  "começar às 12h", e a régua móvel não se reproduziria no Backtest.)
- `executar(prep: Preparado, profile: ExecutionProfile) -> BacktestResult` —
  converte o perfil (`ativo.perfil_para_motor(profile, prep.ficha)`) e chama
  `backtest(..., cache=prep.cache)`; `res.profile = profile`. `ValueError` se
  `profile.timeframe != prep.timeframe`.
- `run_strategy(...)` vira `executar(preparar(..., profile.timeframe, ...), profile)`,
  mesma assinatura de hoje.
- `backtest(..., cache: dict | None = None)`: com cache, guarda só o que é
  caro e pequeno o bastante para não estourar a memória com 20 núcleos:
  `("relogio",)` → `(dias, minuto, dow_iso)` de `build_session_arrays`
  (calculados uma vez; a máscara da janela continua sendo montada por perfil,
  é barata), `("atr", p)` e `("adx", p)` em LRU de no máximo 4 entradas cada.
  O revisor confirmou que `kernel.run` só escreve nos arrays `o_*`: nada em
  cache precisa de cópia. `build_session_arrays` ganha o parâmetro opcional
  `rel=` para receber o trio pronto.

- [ ] **Passo 1: testes falhando.**

```python
def test_executar_compartilhado_igual_ao_isolado(casos_por_estrategia):
    # um Preparado servindo todos os perfis do gabarito do mesmo timeframe
    # tem de dar o mesmo que um Preparado novo por perfil (cache não vaza)
    for (bars, mod, params, tf, inst), perfis in casos_por_estrategia:
        prep = preparar(bars, mod, params, tf, inst)
        for p in perfis:
            novo = executar(preparar(bars, mod, params, tf, inst), p)
            assert assinatura(executar(prep, p)) == assinatura(novo)

def test_executar_recusa_outro_timeframe():
    with pytest.raises(ValueError):
        executar(preparar(bars, mod, params, "M5", inst), ExecutionProfile(timeframe="M1"))

def test_cache_nao_muda_quem_chamou(caso):
    # rodar um perfil não altera sinais nem barras guardados no Preparado
    prep = preparar(...); antes = copia_profunda(prep.sinais, prep.bars)
    executar(prep, perfil_qualquer)
    assert iguais(antes, (prep.sinais, prep.bars))

def test_vela_aberta_recua_a_ultima_vela():
    a = preparar(bars, mod, params, "M5", inst)
    b = preparar(bars, mod, params, "M5", inst, vela_aberta=True)
    assert b.fechada[-1] == a.fechada[-1] - 1 and (b.fechada[:-1] == a.fechada[:-1]).all()
```
- [ ] **Passo 2:** rodar → FALHA (`preparar` não existe).
- [ ] **Passo 3:** implementar.
- [ ] **Passo 4:** `pytest tests/test_motor_camadas.py tests/test_engine.py
  tests/test_run_strategy_ativo.py tests/test_ativo_motor.py -q` → PASSA,
  inclusive o gabarito da Tarefa 1.
- [ ] **Passo 5:** `scripts/foto_win.py conferir antes-camadas` → idêntico.
- [ ] **Passo 6:** mutação (`mutacao` em `preparar`/`executar`/cache) e
  `revisor` em segundo plano; suíte inteira verde. Commit:
  `refactor(motor): preparar e executar em camadas, com cache por perfil`.

## Tarefa 3: a conta da Varredura como função

**Arquivos:**
- Modificar: `core/optimizer.py:215-242` (`_uma`)
- Teste: `tests/test_motor_camadas.py`

**Interfaces (produz):**
`avaliar_resultado(res: BacktestResult, perfil: ExecutionProfile,
janelas: wf.Janelas, trial_id, params: dict) -> dict` — exatamente o dicionário
que `_uma` devolve hoje (inclusive o ramo `n_trades == 0`, com `"holdout":
vazio`). `_uma` passa a ser `run_strategy` + `avaliar_resultado`, e o
`try/except` continua no `_uma`.

- [ ] **Passo 1:** teste falhando: para 3 combinações da grade da foto, `_uma(...)`
  == `avaliar_resultado(executar(prep, perfil), perfil, janelas, i, params)`
  (dicionários iguais, `-inf`/`nan` comparados como iguais).
- [ ] **Passo 2–4:** falha → implementar → passa.
- [ ] **Passo 5:** foto `conferir antes-camadas` idêntico; suíte verde. Commit:
  `refactor(mineracao): avaliar_resultado compartilhado com a busca`.

**Fim da etapa 1:** mostrar ao usuário a foto idêntica e o gabarito; pedir ok
para juntar no `master`. Avisar em destaque: depois do merge, **fechar Captura
e Ordens real e reabrir o `iniciar.bat` fora do pregão** (o papel usa
`core/engine`).

---

# Etapa 2 — Busca, processo separado, banco e controles

## Tarefa 4: catálogo declarativo

**Arquivos:**
- Modificar: `requirements.txt` (`ribs==0.12.0`; instala também scipy,
  scikit-learn e pandas — `core/` continua sem importar scipy)
- Criar: `core/busca/__init__.py`, `core/busca/catalogo.py`
- Teste: `tests/test_busca_catalogo.py`

**Interfaces (produz):**
```python
@dataclass(frozen=True)
class Item:
    nome: str            # "di_periodo", "timeframe", "janela", "dias", "direcao",
                         # "stop", "alvo"
    rotulo: str
    tipo: str            # "lista" | "inteiro" | "real" | "hora" | "dias"
    camada: str          # "essencial" | "filtro"
    degrau: str          # "fixo" | "proporcional" | "minutos"
    padrao: dict         # {"de","ate","passo"} ou {"valores": [...]}
    onde: str            # "param" | "perfil"

def montar_catalogo(estrategia: str, simbolo: str) -> list[Item]
def valores(item: Item, faixa: dict) -> list   # a lista que a busca percorre
def degraus_proporcionais(de: int, ate: int) -> list[int]
POR_ESTRATEGIA: dict[str, dict]   # declarações por estratégia (ver abaixo)
```
Decisões que o catálogo carrega:
- Parâmetros vêm do `params_schema` (camada essencial), faixa de
  `ativo.faixas_do_ativo(simbolo, estrategia)` > schema min/max; `saida` como
  lista de modos.
- `POR_ESTRATEGIA` é a declaração por estratégia **fora do arquivo dela**
  (para não mudar o `codigo_hash`): `{"rompimento_abertura": {"proporcional":
  ["barras_abertura"]}, "adx_direcao": {"proporcional": ["di_periodo",
  "adx_suavizacao"]}, ...}` para as 6 estratégias de hoje (quais parâmetros
  andam em degrau proporcional); estratégia nova pode trazer um `busca = {...}`
  no próprio módulo, que tem prioridade.
- `degraus_proporcionais`: começa no `de`, próximo = `max(v + 1, round(v * 1.08))`
  até `ate` (inclui o `ate`): `2,3,4,…,13,14,15,16,17,18,19,21,…` e `250 → 270`.
- Tempo gráfico: lista `M2, M3, M5, M10, M15, M30` marcados, `M1` e `H1`
  disponíveis desmarcados (como no protótipo).
- Janela: faixa padrão WIN 09:00–17:00 e micros 09:30–16:00 NY (o pregão
  diurno — a ficha do MES vai de 18:00 a 16:30, atravessando a meia-noite, e
  não serve de faixa), passo 30 min, janela mínima 30 min; o fim é inclusivo
  (como `entrada_fim` do menu). Ordem e duração sempre medidas em
  `ativo.hora_para_motor` (relógio de pregão), nunca em hora de NY, e cada
  janela passa por `janela_valida(ini, fim, ficha, fechamento_do_menu)`.
- Dias: 31 máscaras dos 5 dias. Direção: `compra`, `venda`, `ambas`.
- Stop: tipos `pontos`/`atr`/`percentual`, alvo: `pontos`/`multiplicador`/
  `atr`/`percentual` + "sem alvo" (alvo em pontos = 0); faixas do protótipo
  para o WIN escaladas pelo ativo (`faixas_do_ativo` para pontos; ATR 0,5–3,0
  passo 0,25; % 0,10–0,50 passo 0,05; × stop 1,0–4,0 passo 0,5).
- Horário de referência da abertura: **fora da busca** (sempre o da ficha do
  ativo); a linha "Horário da abertura" do protótipo não entra na aba Espaço.

- [ ] **Passo 1: testes falhando.**
```python
def test_degraus_proporcionais():
    v = degraus_proporcionais(2, 300)
    assert v[:12] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert 250 in v and v[v.index(250) + 1] == 270 and v[-1] == 300

def test_catalogo_adx_tem_itens_do_prototipo():
    nomes = [i.nome for i in montar_catalogo("adx_direcao", "WIN$N")]
    assert {"timeframe", "direcao", "janela", "dias", "stop", "alvo",
            "di_periodo", "adx_suavizacao", "amplitude_max", "saida"} <= set(nomes)
    assert "abertura" not in nomes

def test_estrategia_de_abertura_sem_regua_movel():
    assert "abertura" not in [i.nome for i in montar_catalogo("rompimento_ema_abertura", "MES")]

def test_mes_faixas_do_ativo_e_janela_ny():
    cat = {i.nome: i for i in montar_catalogo("adx_direcao", "MES")}
    assert cat["amplitude_max"].padrao == {"de": 5, "ate": 80, "passo": 5}
    assert cat["janela"].padrao["de"] == "09:30"

def test_camadas():
    cat = {i.nome: i for i in montar_catalogo("adx_direcao", "WIN$N")}
    assert cat["di_periodo"].camada == cat["timeframe"].camada == "essencial"
    assert cat["janela"].camada == cat["stop"].camada == "filtro"

def test_parametro_novo_entra_sozinho(monkeypatch):
    # um parâmetro a mais no schema aparece no catálogo sem tocar na busca
```
- [ ] **Passo 2–4:** falha → implementar → passa. Commit:
  `feat(busca): catalogo declarativo do espaco de busca`.

## Tarefa 5: espaço, genoma e casas

**Arquivos:**
- Criar: `core/busca/espaco.py`
- Teste: `tests/test_busca_espaco.py`

**Interfaces (produz):**
```python
@dataclass(frozen=True)
class Combinacao:
    timeframe: str; ini: str; fim: str; dias: tuple[int, ...]; direcao: str
    stop_tipo: str; stop_valor: float; alvo_tipo: str; alvo_valor: float
    params: tuple[tuple[str, object], ...]
    def chave(self) -> str            # JSON canônico, ordenado
    def chave_essencial(self) -> tuple  # (timeframe, params)

class Espaco:
    def __init__(self, catalogo: list[Item], faixas: dict,
                 dims_nicho: tuple[str, ...] = ("timeframe", "ini", "fim", "dias", "direcao")): ...
    n_genes: int
    def decodificar(self, x: np.ndarray) -> Combinacao   # x em [0, 1)^n_genes
    def casa(self, c: Combinacao) -> tuple[int, ...]     # índices nas dims_nicho
    def dims_arquivo(self) -> list[int]                   # tamanhos da grade fina
    def genes_essenciais(self) -> np.ndarray              # máscara booleana dos genes
    def perfil(self, c: Combinacao, perfil_base: dict) -> ExecutionProfile
    def params(self, c: Combinacao) -> dict
    def para_json(self) -> dict ; @classmethod de_json(cls, d) -> "Espaco"
```
As dimensões do nicho são configuráveis (desenho §4.1): qualquer item de
lista do catálogo pode ser dimensão; o padrão é a grade fina do §9.
Regras: cada gene escolhe `min(int(x * n), n - 1)` de uma lista (a pyribs
corta nos limites, então `x = 1,0` acontece); o gene do fim da janela
escolhe só entre fins `>= ini + janela mínima` (nunca janela inválida); janela
recusada por `ativo.janela_valida` sai da lista na montagem. Stop/alvo: um gene
para o tipo, outro para o valor dentro da lista daquele tipo; o perfil recebe só
o campo do tipo escolhido (o resto fica do `perfil_base`).

- [ ] **Passo 1: testes falhando.**
```python
def test_decodificar_e_deterministico_e_cobre_os_limites(espaco):
    assert espaco.decodificar(np.zeros(espaco.n_genes)).timeframe == "M2"
    assert espaco.decodificar(np.ones(espaco.n_genes)).timeframe == "M30"

def test_janela_sempre_valida(espaco):
    for x in np.random.default_rng(1).random((2000, espaco.n_genes)):
        c = espaco.decodificar(x)
        assert minutos_motor(c.fim) - minutos_motor(c.ini) >= 30   # também no MES
        assert janela_valida(c.ini, c.fim, ficha, FECHAMENTO) is None

def test_perfil_igual_ao_do_menu(espaco):
    c = Combinacao(timeframe="M5", ini="10:00", fim="11:30", dias=(2, 4),
                   direcao="compra", stop_tipo="atr", stop_valor=1.5,
                   alvo_tipo="multiplicador", alvo_valor=2.0, params=...)
    p = espaco.perfil(c, PERFIL_BASE)
    assert (p.entrada_inicio, p.entrada_fim, p.dias_semana) == ("10:00", "11:30", (2, 4))
    assert (p.stop_tipo, p.stop_atr_mult, p.alvo_tipo, p.alvo_razao) == ("atr", 1.5, "multiplicador", 2.0)
    assert p.corretagem_por_contrato == PERFIL_BASE["corretagem_por_contrato"]

def test_casa_e_dims(espaco):
    assert len(espaco.dims_arquivo()) == 5

def test_json_ida_e_volta(espaco):
    assert Espaco.de_json(espaco.para_json()).decodificar(x) == espaco.decodificar(x)
```
- [ ] **Passo 2–4** e commit: `feat(busca): espaco e genoma das combinacoes`.

## Tarefa 6: banco `data/buscas.duckdb`

**Arquivos:**
- Criar: `core/busca/banco.py`
- Modificar: `tests/conftest.py` (autouse desvia também `banco.CAMINHO` e
  `banco.PASTA` para `tmp_path`)
- Teste: `tests/test_busca_banco.py`

**Interfaces (produz):** `CAMINHO = db.DATA / "buscas.duckdb"`,
`PASTA = db.DATA / "buscas"` (uma subpasta por busca: `estado.json`,
`controle.json`, `arquivo.pkl`).
```python
def conectar(escrita: bool, tentativas: int = 20, espera_s: float = 0.25)  # contexto
def criar(config: dict) -> int                        # busca_id
def gravar_lote(busca_id: int, combos: list[dict], elites: list[dict],
                contagens: dict) -> None              # uma transação
def ler_busca(busca_id) -> dict | None
def listar() -> list[dict]
def ler_elites(busca_id) -> list[dict]
def ler_combos(busca_id, minimo_trades: int) -> list[dict]
def excluir(busca_id) -> None                          # banco + PASTA/<id>
def marcar_status(busca_id, status: str, **campos) -> None
```
Tabelas (combinação sempre como JSON `nome = valor`, nunca coluna por
parâmetro): `buscas(busca_id, criada_em, simbolo, estrategia, config JSON,
status, testes, distintos, descartados, lote_n, inicio, fim, duracao_s, erro,
historico JSON)` (`lote_n` gravado na MESMA transação do lote); `combos(busca_id, teste_n, casa VARCHAR, combo JSON,
trades, lucro, pf, dd, fr, consistencia, mediana_fold, score, objetivo,
trades_hash, valida BOOL)`; `elites(busca_id, casa, combo JSON, objetivo,
trades, lucro, pf, dd, fr, achado_em INT)`; `elites_hist(busca_id, casa,
teste_n, objetivo)`; `grupos(busca_id, grupo_id, lider_casa, membros JSON,
mediana_obj, n_membros, versao)`.
`conectar` (leitura E escrita) com o arquivo travado por outro processo tenta
de novo no padrão de `db.connect`/`connect_write` (`core/db_manager.py:43-97`)
e, esgotado, levanta `BancoOcupado`: o app mostra a última leitura; o motor
guarda o lote em memória e grava junto com o seguinte, sem derrubar a busca.
`descartar_apos(busca_id, lote_n)` apaga `combos`/`elites_hist` de lotes acima
de `lote_n` (usado na retomada).
O detalhe do nicho fica em `PASTA/<id>/detalhe/<casa>.json` (escrito pelo app,
fora do banco: assim nunca disputa o arquivo com o processo da busca).

- [ ] **Passo 1: testes falhando:** criar/ler/listar; `gravar_lote` atômico
  (erro no meio não deixa metade); `excluir` apaga banco e pasta e recusa
  caminho fora de `PASTA`; `test_leitura_com_escritor_ocupado` (outro processo
  segura a escrita → `BancoOcupado` em tempo limitado, sem travar);
  `test_conftest_isola_buscas` (`banco.CAMINHO` não aponta para `data/`).
- [ ] **Passo 2–4** e commit: `feat(busca): banco proprio buscas.duckdb`.

## Tarefa 7: avaliador (o trabalho de cada núcleo)

**Arquivos:**
- Criar: `core/busca/avaliador.py`
- Teste: `tests/test_busca_avaliador.py`

**Interfaces:**
- Consome: `preparar`/`executar` (T2), `optimizer.avaliar_resultado` (T3),
  `Espaco` (T5).
- Produz:
```python
def iniciar_nucleo(simbolo: str, de, ate, estrategia: str) -> None  # lê o Parquet
def avaliar_grupo(chave_essencial: tuple, tarefas: list[tuple[int, dict]],
                  ctx: dict) -> list[dict]
# ctx = {"espaco": dict, "perfil_base": dict, "janelas": wf.Janelas,
#        "minimo": int, "criterio": str}
# cada saída = {"teste_n", "combo", "casa", "metricas"(geral/folds/score),
#               "objetivo", "valida", "trades_hash", "descartada": str | None}
def objetivo(aval: dict, criterio: str, minimo: int) -> tuple[float, bool]
def teto_de_trades(prep: Preparado, perfil: ExecutionProfile, fim_otimizacao) -> int
```
Decisões:
- Cache LRU de `Preparado` por núcleo (4 entradas), chave = `chave_essencial`.
  Cada núcleo é um processo próprio com fila própria e recebe sempre as mesmas
  chaves (`hash(chave_essencial) % n_nucleos`), senão o cache nunca acerta.
- `objetivo`: as 4 metas do protótipo (`layout-b.html:469`), mapa explícito
  sobre `geral` (período de otimização, holdout fora): `fr` →
  `fator_recuperacao`, `pf` → `profit_factor`, `lucro` → `lucro`, `dd` →
  `-max_dd`; `inf` vira `1e6`. `valida` = `trades ≥ mínimo` **e**
  `passa_filtro` da Varredura (presença em ≥ 60% dos folds); inválida:
  `-1e9 + trades` (a pyribs ainda prefere quem chega mais perto de 400;
  nunca bate uma válida).
- Descarte cedo, só o que é **exato**: `teto_de_trades` = nº de minutos com
  sinal de entrada (no lado da direção) dentro da janela, dos dias e antes do
  fim da otimização — cada trade precisa de um sinal, então teto < mínimo
  ⇒ a combinação nunca chega a 400 e não roda o kernel (`descartada="poucos
  sinais"`). Como a janela e os dias são os da própria combinação, nunca se
  descarta pelo dia inteiro.
- `trades_hash` = sha1 de `(entry_i, side, exit_i)`.

- [ ] **Passo 1: testes falhando.**
```python
def test_bate_com_a_varredura(ctx_win):
    # 20 combinações aleatórias: métricas e score iguais aos de optimizer._uma
    for teste_n, combo in amostra:
        r = avaliar_grupo(...)[0]
        assert r["metricas"] == _uma((teste_n, params, campos_exec, perfil_base, janelas))

def test_descarte_so_quando_impossivel(ctx_win):
    # toda descartada tem, rodando de verdade, menos trades que o mínimo
    for r in resultados:
        if r["descartada"]:
            assert avaliar_de_verdade(r["combo"])["geral"]["trades"] < ctx_win["minimo"]

def test_abaixo_do_minimo_nunca_vale():
    o, valida = objetivo({"geral": {"trades": 399, "fator_recuperacao": 9.0}}, "fr", 400)
    assert not valida and o < -1e8

def test_sem_perda_nao_vira_infinito():
    o, _ = objetivo({"geral": {"trades": 500, "fator_recuperacao": float("inf")}}, "fr", 400)
    assert o == 1e6

def test_menor_drawdown_inverte():
    assert objetivo(geral(dd=100), "dd", 1)[0] > objetivo(geral(dd=200), "dd", 1)[0]
```
- [ ] **Passo 2–4**, mutação, commit: `feat(busca): avaliador com a conta da Varredura`.

## Tarefa 8: o laço da busca (pyribs)

**Arquivos:**
- Criar: `core/busca/motor.py`
- Teste: `tests/test_busca_motor.py`

**Interfaces:**
- Consome: T5, T6, T7.
- Produz:
```python
class Busca:
    def __init__(self, busca_id: int, pasta: Path, semente: int = 0): ...
    def rodar(self, avaliar=None) -> str   # devolve o status final
    # status: "concluida" | "pausada"-> espera | "erro"
def ler_controle(pasta) -> dict   # {"nucleos", "parar_as", "parar_as_ligado",
                                  #  "limite", "pedido": None|"pausar"|"continuar"|"parar"}
def escrever_estado(pasta, estado: dict) -> None   # escrita atômica (tmp + replace)
```
Decisões:
- Arquivo `ribs.archives.GridArchive(solution_dim=n_genes, dims=dims_arquivo(),
  ranges=[(0, n) for n in dims])`, medidas = índices da casa + 0,5.
- Emissores (API conferida na 0.12.0): 4 × `GaussianEmitter(sigma=vetor,
  bounds=[(0, 1)] * n_genes, batch_size=36, seed=semente+i)` com `sigma` 0,02
  nos genes essenciais e 0,12 nos de filtro (mexer mais em horário/dias/stop
  do que no sinal: é o que deixa o cache do núcleo acertar) + 2 ×
  `IsoLineEmitter(iso_sigma=0.05, line_sigma=0.2, batch_size=36, seed=…)`;
  conjuntos iniciais diferentes por emissor (200 aleatórias repartidas, nunca
  as mesmas); `Scheduler(archive, emitters)` ask/tell.
- Um lote = um `ask()`: decodifica, junta combinações iguais (mesma `chave()` já
  avaliada nesta busca não roda de novo: devolve o resultado guardado), agrupa
  por `chave_essencial`, manda cada grupo à fila do núcleo dono da chave
  (processos `multiprocessing` próprios, um por núcleo, com `iniciar_nucleo`),
  e faz `tell` **na ordem do ask** (o resultado não pode depender de qual
  núcleo terminou primeiro).
- Depois de cada lote: `banco.gravar_lote` (com `lote_n`), `elites_hist`
  quando a casa melhora, `arquivo.pkl` (pickle do scheduler + contadores +
  memória de chaves + `lote_n`) escrito atômico com nova tentativa
  (`os.replace` dá PermissionError com o arquivo aberto do outro lado — padrão
  de `core/ponte.py:97-108`). Na retomada, `banco.descartar_apos(lote_n do
  pickle)` apaga o lote que chegou ao banco mas não ao pickle.
- Uma thread de batimento reescreve `vivo_em` a cada 5 s (um lote pesado em M1
  passa de 30 s e não pode parecer queda).
- `estado.json` com `{status, vivo_em, testes,
  distintos, descartados, nichos, bons, melhor, inicio, decorrido_s,
  estimativa_total, historico_nichos (≤ 200 pontos), versao}`.
- Lê `controle.json` a cada lote: núcleos novos → recria o pool no lote
  seguinte; `pausar` → libera o pool e espera (lendo o controle a cada 1 s,
  ainda respeitando "Parar às"); `parar` → status `concluida`; "Parar às" e
  "limite de testes" → `concluida`, o que vier primeiro. "Parar às" vale a
  próxima ocorrência do horário depois do (re)início.
- Estimativa: `testes + taxa_ultimos_10_lotes × segundos_até_parar` (ou o
  limite, se menor); sem nenhum dos dois, sem estimativa.

- [ ] **Passo 1: testes falhando** (avaliador falso, rápido, determinístico,
  passado por `avaliar=`):
```python
def test_lote_grava_e_atualiza_estado(busca_falsa): ...
def test_tell_na_ordem_do_ask(busca_falsa):   # avaliador que embaralha a ordem de término
def test_combinacao_repetida_nao_roda_de_novo(busca_falsa): ...
def test_parar_as_e_limite(busca_falsa, relogio_falso): ...
def test_pausar_e_continuar(busca_falsa): ...
def test_nucleos_mudam_no_proximo_lote(busca_falsa): ...
def test_retomar_apos_queda(busca_falsa):
    # 3 lotes direto == 2 lotes, processo "morre", recarrega o arquivo.pkl, 1 lote
    assert elites_de(direto) == elites_de(retomada)

def test_queda_entre_banco_e_pickle_nao_duplica(busca_falsa):
    # lote 3 gravado no banco, processo morre antes do arquivo.pkl:
    # ao retomar, o lote 3 sai do banco e roda de novo uma vez só
    assert contar_teste_n_repetidos(busca_falsa) == 0

def test_banco_ocupado_nao_derruba(busca_falsa, banco_travado):
    # gravar_lote falha 2x por BancoOcupado: a busca segue e grava tudo depois
```
- [ ] **Passo 2–4**, mutação, revisor, commit: `feat(busca): laco MAP-Elites com pyribs`.

## Tarefa 9: processo separado e controle pelo app

**Arquivos:**
- Criar: `busca.py` (raiz; `python busca.py <busca_id> --pasta P --banco B
  --db-principal D`, com `if __name__ == "__main__"`), `core/busca/controle.py`,
  `core/busca/prioridade.py`
- Teste: `tests/test_busca_processo.py`, `tests/test_busca_controle.py`

**Interfaces (produz, usado pela tela):**
```python
def iniciar(config: dict) -> int          # cria a busca e abre o processo
def continuar(busca_id) -> None           # pausada: pedido; parada/interrompida: abre o processo
def pausar(busca_id) -> None
def parar(busca_id) -> None               # "Parar e guardar"
def ajustar(busca_id, **campos) -> None   # nucleos, parar_as, parar_as_ligado, limite
def ler(busca_id) -> dict                  # estado.json + status do banco + "interrompida"
def ativa() -> int | None                  # busca com processo vivo
def excluir(busca_id) -> None             # recusa com processo vivo
```
Decisões:
- `iniciar`/`continuar` abrem `sys.executable busca.py <id> --pasta …
  --banco … --db-principal …` (sempre os caminhos explícitos: o monkeypatch
  dos testes não chega a um processo filho) com `subprocess.Popen(...,
  creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP |
  BELOW_NORMAL_PRIORITY_CLASS, close_fds=True)` — `CREATE_NO_WINDOW`, como a
  `captura.py:133`, e não `DETACHED_PROCESS` (sem console, cada núcleo abriria
  uma janela). Sobrevive ao app fechado. `prioridade.baixar()` (ctypes,
  `SetPriorityClass`) repete a prioridade dentro do processo; os núcleos herdam.
- Uma busca viva por vez: trava de arquivo `PASTA/rodando.lock` no padrão de
  `captura.travar` (msvcrt, `captura.py:108-121`) — o Windows solta a trava se
  o processo morre. Vivo = a trava não pode ser pega. Nunca `os.kill(pid, 0)`
  (no Windows mata o processo) nem o pid do `Popen` (o `python.exe` do venv é
  um lançador).
- Comandos: `controle.json` escrito atômico (com nova tentativa); o processo lê
  a cada lote e o batimento a cada 5 s.
- Interrompida = status `rodando`/`pausada` no banco e a trava livre.
- `busca.py` nunca importa `ui/` nem abre `db.DB_PATH`; lê barras só do
  Parquet; trata `KeyboardInterrupt`/exceção gravando `erro` e o último lote.
- `scripts/conferir_busca.py <busca_id> [n=10]`: refaz as N melhores elites
  pelo caminho da Varredura (`optimizer._uma`) e compara bit a bit — é a prova
  de "bate exatamente" na tela de verdade.

- [ ] **Passo 1: testes falhando** (todo teste que abre o processo de verdade
  passa `--pasta/--banco/--db-principal` em `tmp_path`):
  `test_nao_abre_banco_principal` (o processo roda 1 lote real em WIN, período
  curto, com `--db-principal` apontando para um arquivo que acusa se aberto);
  `test_sem_janela_por_nucleo` (flags do `Popen`); `test_sobrevive_ao_pai`;
  `test_uma_por_vez`;
  `test_interrompida_detectada`; `test_excluir_recusa_viva`;
  `test_prioridade_abaixo_do_normal` (só Windows).
- [ ] **Passo 2–4**, mutação, revisor, suíte verde.
- [ ] **Passo 5: conferência real (fora do pregão):** busca de 10 min em WIN
  com `adx_direcao`; `scripts/conferir_busca.py` → 10/10 idênticas; anotar
  testes/min com 4 e com 20 núcleos para o usuário.
- [ ] **Passo 6:** commit `feat(busca): processo separado e controles`.

**Fim da etapa 2:** mostrar ao usuário a conferência e a velocidade; pedir ok
para juntar.

---

# Etapa 3 — Agrupamento e detalhe

## Tarefa 10: grupos

**Arquivos:**
- Criar: `core/busca/grupos.py`
- Modificar: `core/busca/motor.py` (reagrupa a cada 5 min e ao parar, grava em
  `grupos` com `versao` nova; o líder vem das elites, que são uma por casa
  fina — a "distância" do agrupamento é a regra de "parecidas" abaixo)
- Teste: `tests/test_busca_grupos.py`

**Interfaces (produz):**
```python
def parecidas(a: Combinacao, b: Combinacao, espaco: Espaco) -> bool
def agrupar(elites: list[dict], combos: list[dict], espaco: Espaco) -> list[dict]
# grupo = {"grupo_id", "lider_casa", "lider": dict, "membros": [combo dicts],
#          "mediana_obj", "n_membros"}
```
Regra de "parecidas" (distância em degraus da lista do catálogo): mesmo tempo
gráfico, direção, tipo de stop e de alvo; cada parâmetro a ≤ 2 degraus; valor
de stop e de alvo a ≤ 2 degraus; início e fim da janela a ≤ 1
degrau; dias com no máximo 1 dia de diferença.
Agrupamento: elites válidas por objetivo decrescente; cada uma entra no
primeiro grupo cujo líder é parecido, senão abre grupo. Membros = combinações
válidas (`trades ≥ mínimo`) parecidas com o líder, contando uma vez cada
`trades_hash`.

- [ ] **Passo 1: testes falhando:** dois líderes iguais-menos-o-tempo-gráfico
  → grupos diferentes; parâmetro a 3 degraus → fora; combinações com o mesmo
  `trades_hash` → um membro só; inválida nunca é membro; 30 variações do mesmo
  ponto viram **um** grupo (anti-objetivo do desenho).
- [ ] **Passo 2–4**, mutação, commit: `feat(busca): agrupamento de campeoes parecidos`.

## Tarefa 11: projeções do mapa e a lista

**Arquivos:**
- Criar: `core/busca/projecao.py`
- Teste: `tests/test_busca_projecao.py`

**Interfaces (produz):**
```python
EIXOS = ("horario", "dias", "direcao")
CORES: dict[str, dict]   # por critério: paradas de cor e marcas da legenda
                         # (fr: 0/1,5/3/4,5/6 do protótipo; pf: 0,8/1,1/1,25/1,4/1,55; trades: 400/1000/1600/2200)
BONS: dict[str, float]   # fr ≥ 3; pf ≥ 1,25; demais = padrão de CRITERIOS
def mapa(busca_id, eixo: str, metrica: str) -> dict
# {"linhas": [tf], "colunas": [rótulo], "casas": [{"linha","coluna","estado":
#   "vazia"|"poucos"|"ok", "valor", "texto", "trades", "membros", "melhor": bool,
#   "casa_fina", "dims": [(rótulo, valor)]}], "n_com_resultado", "n_casas",
#   "bons", "melhor": {...} | None}
def lista(busca_id, metrica: str) -> list[dict]   # uma linha por casa com resultado
def rotulo_dias(mascara: tuple[int, ...]) -> str  # "ter–qui", "seg, qua e sex"
```
Projeção: a casa (tempo × coluna) mostra a melhor elite entre as casas finas
que caem nela. Colunas — horário: os inícios de janela do espaço; dias: **uma
coluna por combinação de dias testada** (decisão do usuário em 03/11; até 31,
com rolagem lateral, ordem: 1 dia, 2 dias… e dentro de cada uma seg→sex);
direção: compra, venda, as duas. Valor `inf` ou acima da
última parada pinta com a cor da ponta.

- [ ] **Passo 1: testes falhando:** projeção pega a melhor; casa só com
  inválidas = "poucos" com o nº de trades; sem nada = "vazia"; `bons` conta
  `fr ≥ 3`; `rotulo_dias((2,3,4)) == "ter–qui"`; lista ordenável por
  fr/pf/trades/membros; "evolução" = até 10 pontos do melhor objetivo da casa
  ao longo de `elites_hist`.
- [ ] **Passo 2–4** e commit: `feat(busca): projecoes do mapa e lista de nichos`.

## Tarefa 12: detalhe do nicho e "Minerar a região"

**Arquivos:**
- Criar: `core/busca/detalhe.py`
- Teste: `tests/test_busca_detalhe.py`

**Interfaces (produz):**
```python
def detalhe(busca_id, casa_fina: str) -> dict
# {"campeao": combo+métricas, "kpis": {fr, fr_mediano, pf, trades, maior_queda, membros},
#  "hora_dia": {"horas": [...], "dias": [...], "valores": [[float|None]], "dentro": [[bool]]},
#  "por_ano": [{"ano", "pct_lucro"|None, "holdout": bool}],
#  "espalhamento": [{"item", "testada": (a, z), "membros": (a, z), "mediana", "campeao"}],
#  "curva": {"x": [...], "y": [...]}, "moeda": str}
def regiao_para_varredura(busca_id, casa_fina: str) -> dict
# valores do menu: timeframe, entrada_inicio, entrada_fim, dias_semana, direcao,
# stop_tipo, alvo_tipo e, por campo minerável, {"on", "de", "ate", "passo", "valor"}
def campeao_para_backtest(busca_id, casa_fina: str) -> dict   # params + perfil completos
```
Decisões:
- Membros usados nas contas: até 24 (os de maior objetivo, campeão incluso).
- Hora × dia: cada membro roda com a janela do espaço inteira e os 5 dias (o
  resto igual); média líquida por trade por degrau de hora de entrada × dia;
  `None` com menos de 40 trades; `dentro` marca a janela e os dias do nicho;
  linhas do degrau antes do início até o degrau depois do fim.
- Por ano: % dos membros com lucro líquido no ano (trades do período de
  otimização); ano inteiro no holdout = `holdout: True`, sem valor.
- Curva: patrimônio do campeão pela data de saída, período de otimização,
  no máximo 400 pontos.
- Faixas da região: de = menor valor entre os membros, até = maior, passo = o
  do schema/`SCHEMA_EXECUCAO` (não o proporcional); janela de = menor início, até
  = maior fim; dias e direção do campeão.
- Roda no processo do app (só leitura do banco da busca), numa thread; guardado
  em `PASTA/<id>/detalhe/<casa>.json` com a `versao` dos grupos (vale como os
  "dados do detalhe" do desenho §5, sem disputar o banco com a busca). Medir o
  tempo com 24 membros na Tarefa 12; a gaveta mostra os KPIs na hora e os
  quatro quadros quando ficarem prontos.

- [ ] **Passo 1: testes falhando** com uma busca pequena gravada no banco de
  teste: KPIs do campeão = os da elite; `fr_mediano` = mediana dos membros;
  hora × dia soma, em trades, o mesmo que os backtests expandidos; ano no
  holdout sem valor; faixas da região contêm todos os membros e o campeão;
  `campeao_para_backtest` rodado por `run_strategy` dá as métricas da elite.
- [ ] **Passo 2–4**, mutação, revisor, commit:
  `feat(busca): detalhe do nicho e faixas da regiao`.

**Fim da etapa 3:** mostrar ao usuário, em texto curto, os 5 melhores grupos de
uma busca real (sem tela ainda); pedir ok para juntar.

---

# Etapa 4 — A tela e o "Minerar a região"

Antes de começar: carregar as skills `frontend-design`, `design-critique`,
`accessibility-review` e `ux-copy`; o agente `designer-ui` revisa cada tarefa
contra o `layout-b.html`. Cores só dos tokens de `ui/assets/style.css`.

## Tarefa 13: subtela e esqueleto

**Arquivos:**
- Modificar: `ui/app.py:195-198` (opção "Busca automática" entre Varredura e
  Backtest; bloco `mine-bloco-busca`) e `ui/callbacks.py` — os callbacks que
  hoje tratam "tudo que não é backtest" como Varredura: `modo`
  (`callbacks.py:1043-1061`, ganha a saída `mine-bloco-busca` e esconde
  Varredura/`sec-mineracao` na busca), `menu_abas` (:115), `pontinhos` (:128),
  `faixas` (:1120)
- Criar: `ui/components/busca_panel.py`, `ui/assets/busca.css`
- Teste: `tests/test_busca_tela.py`

**Interfaces (produz):** `busca_panel.painel() -> html.Div` com os ids do
protótipo prefixados `busca-` (faixa `busca-k-*`, abas `busca-v-mapa|lista|esp`,
mapa `busca-mapa`, lista `busca-lista`, espaço `busca-esp`, trilho
`busca-rail`, gaveta `busca-gaveta`, confirmação `busca-cf`), um
`dcc.Interval(id="busca-relogio", interval=2000)` e `dcc.Store`s
`busca-sel` (busca aberta), `busca-ver` (versão lida).

- [ ] **Passo 1:** testes de estrutura (subtela existe na ordem certa; nenhum
  texto visível fora de rótulos/títulos — todo `(?)` tem `aria-label`).
- [ ] **Passo 2:** implementar o esqueleto estático igual ao protótipo
  (estado "Parada", sem busca).
- [ ] **Passo 3:** `tests/test_callbacks_sem_ciclo.py`, `scripts/campos_menu.py`,
  `scripts/referencia_telas.py conferir` verdes.
- [ ] **Passo 4:** conferir na tela (preview `dataframe`, fora do pregão, app
  real fechado) lado a lado com o protótipo; screenshot ao usuário. Commit.

## Tarefa 14: trilho de controle

**Arquivos:**
- Criar: `ui/callbacks_busca.py` (registrado em `ui/callbacks.py:register`)
- Modificar: `ui/callbacks.py` (extrair `perfil_do_menu(...)` de `minerar`
  para a busca usar os MESMOS fixos do menu; `minerar` passa a chamá-la)
- Teste: `tests/test_busca_tela.py`

Comportamento (tabela de estados do protótipo, `S` em `layout-b.html:692-703`):
botões habilitados por estado; Iniciar monta a config (catálogo + faixas da
aba Espaço + `perfil_do_menu` + período/holdout/wf do menu + regras) e chama
`controle.iniciar`; Pausar/Continuar/Parar e guardar/Nova busca; "Parar às" e
limite chamam `ajustar` na hora; núcleos com "aplicando" até o próximo
`estado.json` confirmar; padrão 20/4 enquanto o usuário não mexer; buscas
salvas da estratégia+ativo do menu, lixeira com confirmação e desligada (com
o motivo no `(?)`) para a busca viva; menu à esquerda travado ("em uso") com
busca existente.

- [ ] **Passo 1:** testes: `perfil_do_menu` == perfil que `minerar` montava
  (mesmos States); botões por estado (5 estados); excluir pede confirmação.
- [ ] **Passo 2–4:** implementar; sem ciclo; campos do menu iguais.
- [ ] **Passo 5:** na tela: iniciar uma busca de verdade, pausar, continuar,
  parar; fechar o app com ela rodando e reabrir (continua). Commit.

## Tarefa 15: faixa de andamento e mapa

**Arquivos:**
- Modificar: `ui/components/busca_panel.py`, `ui/callbacks_busca.py`
- Criar: `ui/assets/busca_mapa.js` (tooltip, setas/Home/End/Enter, pulso da casa
  nova, foco — no cliente, lendo `data-*` das casas)

Mapa por `projecao.mapa(...)`, refeito só quando `estado.versao` muda; casas
52×40, listrado/vazio/★, legenda contínua, "N de M com resultado", seletor de
colunas e de cor; faixa: testes "de ~N", nichos, bons, melhor (clique foca a
casa), decorrido/faltam e linha dos nichos acesos.

- [ ] Testes de callback (mapa reconstrói só com versão nova; texto das casas
  por estado) → implementar → conferir na tela com a busca da T14 rodando
  (casa nova pulsa, teclado anda). Commit.

## Tarefa 16: lista e espaço de busca

Lista por `projecao.lista` (selos melhor/bom/fraco/poucos membros/novo, barras,
evolução, ordenação, "Só bons", "Mostrar todos"); aba Espaço gerada do
catálogo (itens, faixas, passos, chips; "proporcional" em ciano), editável só
sem busca; bloco "Fixos" lido de `perfil_do_menu`; Meta e mín. de trades.

- [ ] Testes: item novo no catálogo aparece na aba sem mudar a tela; aba
  travada com busca existente. Implementar, conferir na tela. Commit.

## Tarefa 17: gaveta do nicho, Backtest e "Minerar a região"

Gaveta lateral por cima (foco preso, Esc devolve o foco à casa, ← → vizinho na
ordem da visão), selos e "parcial" com a busca rodando, 6 KPIs, hora × dia,
por ano, espalhamento, curva (`detalhe.detalhe`). "Abrir o campeão no
Backtest" tem callback próprio: o `_carregar_combinacao` da Varredura
(`callbacks.py:900-932`) só escreve os campos `val`, então este escreve, com
`allow_duplicate=True`, os `val`, os `e-*` da lista `MENU_COMBINACAO`
(tempo gráfico, janela, dias, direção, tipos de stop/alvo), `excluir-holdout`,
`store-combinacao` (origem nova `"busca"` em `ORIGEM_GATILHO`, :881),
`mine-subtela = "backtest"` e dispara `btn-run`. "Minerar a região" escreve
`regiao_para_varredura` nos campos do menu (Outputs com
`allow_duplicate=True`, sem editar `controls.py`) e troca para a Varredura;
liberado com a busca rodando.

- [ ] Testes: Minerar a região preenche exatamente as faixas devolvidas;
  Abrir o campeão dá no Backtest as métricas da elite; sem ciclo;
  `scripts/campos_menu.py` verde. Implementar; conferir na tela os dois
  botões com uma busca real. Commit.

## Tarefa 18: acabamento e entrega

- [ ] `design-critique` + `accessibility-review` + `ux-copy` sobre a tela pronta
  (screenshots dos 5 estados); aplicar só o que não desvia do protótipo
  (desvio: perguntar).
- [ ] `referencia_telas.py conferir`, `campos_menu.py`, suíte inteira verde.
- [ ] Agente `documentador`: CHANGELOG, README, METODOLOGIA, "Onde estamos" e
  as armadilhas novas no `AGENTS.md` (banco próprio, processo à parte, uma
  busca por vez, "Minerar a região").
- [ ] Ok do usuário → juntar no `master`. Avisar em destaque: **feche e abra o
  `iniciar.bat`** para ver a tela nova.
