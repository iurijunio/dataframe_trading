# Modo Candidata — plano de execução, etapa 3 (tamanho e plano de operação)

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.
> Cada passo é uma caixa (`- [ ]`) e o ciclo é sempre: teste que falha →
> rodar e ver falhar → implementação mínima → rodar e ver passar → commit.

**Objetivo:** fechar a tela Candidata com o bloco 5 — quantos contratos operar,
quando reduzir, quando desligar — e gravar o plano de operação que a incubação
(projeto C) vai ler.

**Arquitetura:** o cálculo novo mora em `core/tamanho.py` (nada de Dash), lê a
mesma `leitura_robustez` que os blocos 1 e 2 já usam e devolve dicionários
puros. A gravação mora em `core/plano.py`, com tabela nova `planos_operacao`.
A tela ganha um bloco (tabela com mapa de calor, como os outros) e um botão.

**Tecnologia:** Python 3.12, numpy, DuckDB, Dash 4.4.1. **Sem scipy, de
propósito.**

**Desenho de origem:** [PLANO-CANDIDATA.md](PLANO-CANDIDATA.md) §4.5, §5
(portões 6 e 7), §6.3, §6.4 e §8 fase 5.

---

## Restrições globais

- Nada em `core/` importa Dash.
- **Sem scipy.** `Φ⁻¹` e afins já existem em `core/`; reusar.
- Teste nunca toca `data/database.duckdb`: sempre banco temporário.
- Python é `.venv/Scripts/python.exe`; testes com `python -m pytest -q`.
- Commits: `git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit`.
- **Não tocar** em `ui/components/controls.py` e `ui/components/wfa_matriz.py`
  (o usuário tem edições não commitadas ali).
- Linguagem de tela em **português simples, sem jargão nem sigla**. Todo número
  na tela tem (?) dizendo o que é, o que é bom e o que é ruim.
- Número na tela vai em **tabela com mapa de calor**, nunca em cartão novo.
- Um `Output` do Dash tem **um dono só**. Depois de mexer em callback, rodar
  `tests/test_callbacks_sem_ciclo.py`.
- Dado que falta vira **"não medido"** — nunca um número inventado, nunca um
  visto verde.

## Decisão do usuário que este plano trava

**Camada 4 travada** (18/09/2026). Correção importante em relação à pergunta
feita: a camada 4 que a mineração varre não são só os limites do dia — são
`alvo_pontos`, `stop_pontos`, `breakeven_pct`, `step_gatilho_pct`,
`step_distancia_pct` e `trailing_pontos` (`wfa_runner.CAMPOS_EXECUCAO_NOMES`).
Travar significa: **a primeira janela escolhe o stop, o alvo e as proteções, e
todas as janelas seguintes ficam com esses valores**, reotimizando apenas os
parâmetros da estratégia.

A caixa de marcar do desenho original continua existindo (decisão 9 do
PLANO-WFA), mas **nasce marcada como travada**, e o valor vai gravado no
walk-forward e dentro do plano de operação. Travar no valor da primeira janela,
e não no melhor do período inteiro, é o que evita olhar o futuro: o melhor do
período inteiro só é conhecido depois que o período acabou.

---

## O que já existe e deve ser reaproveitado

| já existe | onde | serve para |
|---|---|---|
| `leitura_robustez` (bootstrap, dois recortes) | `core/candidata.py:67` | a matéria-prima do tamanho e do disjuntor |
| `pior_dos_recortes` | `core/candidata.py:116` | pior entre curva inteira e 12 meses, por métrica |
| `risco_de_desligar(boot, limite)` | `core/candidata.py:189` | chance de desligar uma estratégia sadia |
| `por_pregao(saida, liquido, de, ate)` | `core/candidata.py:37` | resultado por pregão, dias parados valendo zero |
| `limites_oos(passos)` | `core/candidata.py:171` | começo e fim reais da curva fora da amostra |
| `calcula_horizonte(detalhes)` | `core/candidata.py:152` | pregões até a próxima reotimização |
| `_tabela`, `linhas`, `_tom` | `ui/components/candidata_panel.py` | a tabela com mapa de calor |
| `portao`, `veredito` | `core/candidata.py:372,778` | contrato dos portões |
| `wfa_store.salvar/detalhes/excluir` | `core/wfa_store.py` | retrato do WFA e cascata |
| `optimizer.excluir_salva` | `core/optimizer.py` | a outra ponta da cascata |

---

## Estrutura de arquivos

| arquivo | responsabilidade |
|---|---|
| `core/tamanho.py` **(novo)** | perda de referência por contrato, contratos, risco efetivo, margem, disjuntor em dois níveis |
| `core/plano.py` **(novo)** | gravar, listar, ler e excluir plano de operação |
| `core/schema.sql` | tabela `planos_operacao` + sequência |
| `core/wfa.py` | `rodar(...)` aceita travar a camada 4 |
| `core/wfa_store.py` | grava/lê `camada4_travada`; cascata para `planos_operacao` |
| `core/optimizer.py` | cascata para `planos_operacao` |
| `ui/components/candidata_panel.py` | bloco 5: entradas e tabela |
| `ui/callbacks_candidata.py` | callbacks do bloco 5 e do botão Gravar |
| `ui/components/wfa_panel.py` + `ui/callbacks.py` | a caixa "travar stop e alvo" |
| `configs/instruments/win.yaml` | nada — a margem é do operador, entra pela tela |

---

## Tarefa 1: perda de referência por contrato ✅ (18/09/2026)

**Arquivos:**
- Criar: `core/tamanho.py`
- Testar: `tests/test_tamanho.py` — 24 testes, 8 mutações provadas

**Interfaces produzidas:**
```python
def por_contrato(pnl_dia, contratos: int) -> np.ndarray
def cvar_pregao(pnl_contrato, fracao=0.05) -> dict   # valor, quantos, fracao, motivo
def stops_do_dia(perfil: dict, observado: int | None = None) -> int | None
def dia_ruim(perfil, point_value, custo_por_trade=0.0, trades_no_dia=None) -> float | None
def trava_do_indice(preco_indice, point_value, pct=10.0) -> float | None
def perda_referencia(pnl_dia, contratos, perfil, point_value, *,
                     piso=None, custo_por_trade=0.0, trades_no_dia=None) -> dict
```
`perda_referencia` devolve `{"valor", "de_onde", "cvar", "quantos", "fracao",
"pior_dia", "dia_ruim", "motivo"}`.

### Dois candidatos, e vale o pior

A conta de contratos precisa de **uma** perda de referência por contrato:

1. **média dos 5% piores pregões**: o dia ruim típico, medido. Não é o teto da
   cauda — metade das perdas da cauda é maior, e o (?) diz isso. O retorno traz
   `quantos` e `fracao` de verdade, porque em 67 pregões "5%" são 4 dias, que
   são 6%;
2. **um dia ruim de execução**: todos os stops que o dia permite batem e o
   último sai com o dobro do tamanho porque não havia preço, mais o custo dos
   giros. Só existe com stop em pontos.

É o pregão, não o trade, porque o dia empilha perdas e é nele que a camada 4
impõe limite.

**O pior pregão já ocorrido é leitura, não candidato** (decisão do usuário,
18/09/2026). Uma média nunca passa do pior do grupo: deixá-lo concorrer
desligaria o candidato 1 — testado em 20.000 curvas, a média nunca venceria.
E ele é um recorde, que só piora conforme o histórico cresce; um único registro
torto passaria a decidir o tamanho da posição sozinho.

**"Dia ruim de execução", não trava de índice** (mesma decisão). Uma trava de
10% no WIN custa ~R$ 2.600 por contrato, dez vezes mais: dimensionar por ela
deixaria quase todo capital em 1 contrato ou nenhum. `trava_do_indice` calcula
esse número para a tela **avisar**, sem dimensionar.

### Quantos stops cabem no dia

Vale o **menor** entre `max_prejuizos_dia` e `max_trades_dia` que esteja
ligado; sem nenhum dos dois, o maior número de operações que um pregão da curva
teve. Num dia só de stops toda operação é perdedora, então os dois campos
contam a mesma coisa e o motor para no primeiro que chegar. **Zero nos dois
significa desligado no motor**, não "um trade" — tratar zero como um faria o
perfil sem trava nenhuma receber a referência mais branda de todas.

`limite_perda_contrato`, quando existe, serve de teto: o motor confere depois
que um trade fecha e bloqueia entrada nova, nunca fecha posição aberta, então o
trade que estoura passa inteiro. É cota superior, não a conta exata do motor
(que ainda mede o limite em pontos brutos).

### O que a função se recusa a medir

Posição variável no backtest (dividir por número fixo de contratos não vale),
curva sem pregão, pregão sem valor gravado (o `nan` sumia em silêncio dentro da
média e ainda vazava para a tela, onde nem é JSON válido), menos de 21 pregões
(com 20, 5% arredondado para cima ainda é um dia só, e a "média dos piores"
seria o pior) e referência abaixo do menor movimento do instrumento (um centavo
de referência viraria 100 mil contratos).

Recusar **dimensionar** não apaga as leituras: o pior pregão e o dia ruim de
execução continuam no retorno, porque o dia ruim nem sai da curva e apagar
número medido faria a tela escrever "não medido" sobre ele. E a recusa de
amostra pequena do desenho (§5, 100 operações fora da amostra) é de quem chama,
não desta função — aqui a guarda de 21 pregões só barra entrada degenerada.

- [ ] **Passo 1: o teste que falha**

```python
# tests/test_tamanho.py
import numpy as np
import pytest

from core import tamanho


def test_por_contrato_divide_pelo_tamanho_do_backtest():
    """O backtest rodou com 2 contratos; a conta de tamanho precisa da perda
    de UM contrato, senão dimensionar em cima dela conta o mesmo contrato
    duas vezes."""
    pnl = np.array([-200.0, 100.0, -50.0])
    assert list(tamanho.por_contrato(pnl, 2)) == [-100.0, 50.0, -25.0]


def test_cvar_pregao_e_a_media_dos_piores_nao_o_pior():
    """CVaR é média da cauda. 100 dias, os 5 piores valendo -100..-96:
    a média deles é -98, não -100."""
    pnl = np.concatenate([np.array([-100.0, -99.0, -98.0, -97.0, -96.0]),
                          np.full(95, 10.0)])
    assert tamanho.cvar_pregao(pnl) == pytest.approx(-98.0)


def test_cvar_pregao_sem_dado_nao_inventa():
    assert tamanho.cvar_pregao(np.array([])) is None


def test_dia_de_trava_usa_todos_os_stops_do_dia_e_dobra_o_ultimo():
    """3 trades por dia, stop de 300 pontos, R$ 0,20 por ponto = R$ 60 por
    stop. Dois stops cheios mais um com o dobro: 60 × 4 = 240."""
    perfil = {"stop_tipo": "pontos", "stop_pontos": 300, "max_trades_dia": 3}
    assert tamanho.dia_de_trava(perfil, 0.20) == pytest.approx(240.0)


def test_dia_de_trava_sem_limite_de_trades_conta_um_stop():
    perfil = {"stop_tipo": "pontos", "stop_pontos": 300, "max_trades_dia": 0}
    assert tamanho.dia_de_trava(perfil, 0.20) == pytest.approx(120.0)


def test_dia_de_trava_com_stop_por_atr_nao_e_medido():
    perfil = {"stop_tipo": "atr", "stop_pontos": 300, "max_trades_dia": 2}
    assert tamanho.dia_de_trava(perfil, 0.20) is None


def test_perda_referencia_vale_o_pior_dos_tres_e_diz_de_onde_veio():
    """Um dia isolado de -900 é pior que o CVaR (-98) e que a trava (-240):
    dimensionar pelo CVaR aqui seria escolher o número mais confortável."""
    pnl = np.concatenate([np.array([-900.0, -99.0, -98.0, -97.0, -96.0]),
                          np.full(95, 10.0)])
    perfil = {"stop_tipo": "pontos", "stop_pontos": 300, "max_trades_dia": 3}
    r = tamanho.perda_referencia(pnl, 1, perfil, 0.20)
    assert r["valor"] == pytest.approx(900.0)      # sempre positivo
    assert r["de_onde"] == "o pior pregão que já aconteceu"
    assert r["trava"] == pytest.approx(240.0)


def test_perda_referencia_sem_pregao_nenhum_nao_e_medida():
    r = tamanho.perda_referencia(np.array([]), 1, {}, 0.20)
    assert r["valor"] is None and r["motivo"]
```

- [ ] **Passo 2: rodar e ver falhar**

`python -m pytest tests/test_tamanho.py -q` → falha com
`ModuleNotFoundError: core.tamanho`.

- [ ] **Passo 3: implementar o mínimo**

```python
"""Quantos contratos, e quando reduzir ou desligar.

Separado de `candidata.py` de propósito: lá moram os portões (aprova ou
reprova a estratégia); aqui mora o dimensionamento, que só faz sentido
DEPOIS de aprovada e que o usuário mexe (risco por trade, margem).
"""
import numpy as np


def por_contrato(pnl_dia, contratos: int):
    return np.asarray(pnl_dia, dtype=float) / max(int(contratos or 1), 1)


def cvar_pregao(pnl_contrato, fracao: float = 0.05) -> float | None:
    x = np.asarray(pnl_contrato, dtype=float)
    if not len(x):
        return None
    k = max(1, int(np.ceil(len(x) * fracao)))
    return float(np.sort(x)[:k].mean())


def dia_de_trava(perfil: dict, point_value: float | None) -> float | None:
    if not point_value or (perfil or {}).get("stop_tipo") != "pontos":
        return None
    stop = float((perfil or {}).get("stop_pontos") or 0.0)
    if stop <= 0:
        return None
    n = max(int((perfil or {}).get("max_trades_dia") or 0), 1)
    return stop * float(point_value) * (n + 1)


def perda_referencia(pnl_dia, contratos, perfil, point_value) -> dict:
    um = por_contrato(pnl_dia, contratos)
    cvar = cvar_pregao(um)
    pior = float(um.min()) if len(um) else None
    trava = dia_de_trava(perfil, point_value)
    candidatos = [
        (abs(cvar) if cvar is not None and cvar < 0 else None,
         "a média dos 5% piores pregões"),
        (abs(pior) if pior is not None and pior < 0 else None,
         "o pior pregão que já aconteceu"),
        (trava, "um dia de trava, com todos os stops do dia"),
    ]
    validos = [(v, d) for v, d in candidatos if v]
    if not validos:
        return {"valor": None, "de_onde": None, "cvar": cvar, "pior_dia": pior,
                "trava": trava,
                "motivo": ("a curva não tem nenhum pregão de prejuízo para "
                           "servir de referência de risco")}
    valor, de_onde = max(validos)
    return {"valor": valor, "de_onde": de_onde, "cvar": cvar,
            "pior_dia": pior, "trava": trava, "motivo": None}
```

- [ ] **Passo 4: rodar e ver passar**

`python -m pytest tests/test_tamanho.py -q` → 8 passam.

- [ ] **Passo 5: provar que os testes pegam o defeito**

Quebrar de propósito, um de cada vez, e conferir que **um teste específico**
falha; depois desfazer:
- `cvar_pregao` devolvendo `x.min()` em vez da média da cauda;
- `perda_referencia` usando `min(validos)` em vez de `max`;
- `dia_de_trava` com `(n)` em vez de `(n + 1)`.

- [ ] **Passo 6: commit**

```bash
git add core/tamanho.py tests/test_tamanho.py
git commit -m "feat(tamanho): perda de referencia por contrato, o pior de tres leituras"
```

---

## Tarefa 2: contratos, risco efetivo e margem ✅ (18/09/2026)

**Arquivos:**
- Modificar: `core/tamanho.py`
- Testar: `tests/test_tamanho.py` — 40 testes, 12 mutações provadas

**Interfaces produzidas:**
```python
def contratos(capital, risco_pct, perda_ref, margem=None, uso_margem_pct=50.0) -> dict
```
devolve `{"n", "por_risco", "por_margem", "por_folga", "limite",
"risco_pedido_pct", "risco_efetivo_pct", "perda_ref", "margem",
"uso_margem_pct", "motivo"}`.

### As decisões

- **O risco é por PREGÃO, não por operação.** A perda de referência é de um dia
  inteiro; quem digita 1% está aceitando 1% no dia. Chamar de "risco por trade"
  — como este plano e o §4.5 chamavam — faria quem opera três vezes por dia
  achar que aceitou o triplo. Vale para o campo da tela, o (?) e as mensagens.
- **Três contas, vale a menor:** risco, garantia, e **garantia mais prejuízo do
  dia juntos** (`capital ≥ n × (margem + perda_ref)`). Sem a terceira, nada
  impede a garantia comer 45% do capital e o prejuízo do mesmo dia pedir mais
  do que os 55% que sobraram.
- **Piso inteiro, e todas as contas seguintes usam o inteiro.** Entre 1 e 2
  contratos o risco dobra; "1%" vira ficção se a tela guardar o fracionário.
  Invariante testada: o risco efetivo nunca passa do pedido.
- **`n = 0` não é erro: é reprovação por capital insuficiente**, e o `motivo`
  diz **todas** as contas que zeraram — culpar só uma manda o usuário mexer num
  dial que não resolve.
- **Empate aparece no `limite`** ("risco e margem"): dizer só uma faria o
  usuário subir o risco e não ver contrato a mais, sem explicação.
- **Margem em branco não bloqueia** e não vira zero: as contas 2 e 3 ficam de
  fora, e a tela avisa que a garantia não foi conferida. Garantia negativa e
  folga fora de 0–100% são recusadas com motivo, em vez de virar número.
- **`uso_margem_pct`** (padrão 50%) vira dial na tela (tarefa 6) e vai gravado
  no plano. A tela precisa dizer **qual** margem digitar: intradiária ou cheia
  mudam o número de contratos em 10 a 30 vezes.

- [ ] **Passo 1: o teste que falha**

```python
def test_contratos_pelo_risco_arredonda_para_baixo():
    """R$ 100.000, 1% = R$ 1.000 de risco; perda de referência R$ 300 por
    contrato dá 3,33 contratos — operam-se 3, nunca 4."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0)
    assert r["n"] == 3 and r["por_risco"] == 3
    assert r["limite"] == "risco"


def test_risco_efetivo_e_do_inteiro_nao_do_fracionario():
    """3 contratos × R$ 300 = R$ 900 = 0,9% do capital. Mostrar 1% seria
    mentira confortável."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0)
    assert r["risco_efetivo_pct"] == pytest.approx(0.9)
    assert r["risco_pedido_pct"] == 1.0


def test_margem_pode_ser_o_limite_e_a_tela_precisa_saber_qual_foi():
    """Risco daria 3 contratos; com metade de R$ 100.000 em garantia e
    margem de R$ 20.000 por contrato, só cabem 2."""
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=20_000.0)
    assert r["n"] == 2 and r["por_margem"] == 2
    assert r["limite"] == "margem"


def test_sem_margem_informada_o_limite_e_o_risco_e_fica_registrado():
    r = tamanho.contratos(100_000.0, 1.0, 300.0, margem=None)
    assert r["por_margem"] is None and r["limite"] == "risco"


def test_zero_contratos_e_reprovacao_explicita_por_capital():
    """R$ 5.000 com 1% de risco = R$ 50, contra perda de referência de
    R$ 300: nem o contrato mínimo cabe."""
    r = tamanho.contratos(5_000.0, 1.0, 300.0)
    assert r["n"] == 0 and "capital" in r["motivo"]


def test_sem_perda_de_referencia_nao_inventa_contratos():
    r = tamanho.contratos(100_000.0, 1.0, None)
    assert r["n"] == 0 and r["risco_efetivo_pct"] is None and r["motivo"]
```

- [ ] **Passo 2: rodar e ver falhar** (`AttributeError: contratos`).

- [ ] **Passo 3: implementar**

```python
def contratos(capital, risco_pct, perda_ref, margem=None,
              uso_margem_pct: float = 50.0) -> dict:
    base = {"por_risco": None, "por_margem": None, "limite": None,
            "risco_pedido_pct": float(risco_pct),
            "risco_efetivo_pct": None, "perda_ref": perda_ref,
            "margem_usada": margem}
    if not perda_ref or perda_ref <= 0 or not capital or capital <= 0:
        return {**base, "n": 0,
                "motivo": ("sem perda de referência ou sem capital "
                           "informado, não dá para dizer quantos contratos")}
    por_risco = int(capital * float(risco_pct) / 100.0 // perda_ref)
    por_margem = (int(capital * uso_margem_pct / 100.0 // margem)
                  if margem else None)
    n = por_risco if por_margem is None else min(por_risco, por_margem)
    limite = ("margem" if por_margem is not None and por_margem < por_risco
              else "risco")
    motivo = None
    if n <= 0:
        motivo = ("o capital não comporta nem 1 contrato: "
                  + ("a garantia exigida é maior que a parte do capital "
                     "reservada para margem" if limite == "margem" else
                     "1 contrato já arrisca mais do que o limite pedido"))
    return {**base, "n": max(n, 0), "por_risco": por_risco,
            "por_margem": por_margem, "limite": limite,
            "risco_efetivo_pct": (n * perda_ref / capital * 100
                                  if n > 0 else None),
            "motivo": motivo}
```

- [ ] **Passo 4: rodar e ver passar.**

- [ ] **Passo 5: provar os testes** — trocar `//` por `/` (fracionário vaza),
  usar `max` em vez de `min` entre risco e margem, e calcular o risco efetivo
  com `capital × risco_pct` em vez do inteiro. Cada quebra derruba um teste
  nomeado; desfazer.

- [ ] **Passo 6: commit**

```bash
git add core/tamanho.py tests/test_tamanho.py
git commit -m "feat(tamanho): contratos pelo pior entre risco e margem, com risco efetivo do inteiro"
```

---

## Tarefa 3: o disjuntor em dois níveis ✅ (18/09/2026)

**Arquivos:**
- Modificar: `core/tamanho.py`, `core/robustez.py` (a faixa por pregão)
- Testar: `tests/test_tamanho.py`, `tests/test_robustez.py` — 95 testes nos
  dois arquivos, 6 mutações provadas nesta tarefa

**Interfaces produzidas:**
```python
def limite_por_alarme(quedas, alarme_pct: float) -> float | None
def disjuntor(leitura, capital, n_contratos, perfil,
              alarme_reduzir=20.0, alarme_desligar=5.0) -> dict
```
`nivel1` traz `queda`, `perdas_seguidas`, `faixa_por_pregao`, `lucro_no_prazo`,
`alarme_pct` e `acao`; `nivel2` traz `queda`, `pct`, `alarme_pct`,
`risco_de_desligar_pct` e `acao`; fora deles, `recorte`, `dias_sem_topo`,
`limite_dia_reais`, `limite_dia_trades`, `horizonte` e `motivo`.
`robustez.bootstrap` ganhou `envelope_p10/p50/p90`.

### Escolhe-se a taxa de alarme falso, não o percentil

Gatilho único é mau detector: no `dd_p95` desliga-se uma estratégia **sadia**
em ~5% dos ciclos, e uma morta só depois de 20% do capital ter ido.

| nível | gatilho | ação |
|---|---|---|
| 1 | queda passa do limite de reduzir (20% de alarme falso), sequência de dias perdendo passa do p95, ou o acumulado sai por baixo da faixa do pior décimo | reduzir para 1 contrato |
| 2 | queda chega ao limite de desligar (5% de alarme falso) | desligar e reotimizar |

**O limite em reais é consequência da taxa escolhida.** O desenho anterior
fixava o nível 2 no p95 do sorteio e media a chance de desligar à toa contra o
mesmo sorteio: dava **5% sempre, por construção**, e um número que não varia
não calibra nada. Invertida a ordem, mexer no dial muda os dois de verdade.
Pelo mesmo motivo o nível 1 saiu da queda típica — metade dos caminhos de uma
estratégia sadia passa dela, e reduzir posição viraria cara ou coroa.

**A faixa é dia a dia.** `robustez.bootstrap` guarda o acumulado por pregão nos
percentis 10, 50 e 90. O gatilho do desenho ("a equity sai do p10 do
envelope") só funciona assim: comparar o total do fim do prazo só responde
quando o prazo acabou. Custa um percentil sobre a matriz que o laço já
percorre, e é a mesma faixa que §4.5 exige no plano em 3, 6 e 12 meses.

**Mesma régua nos dois níveis.** Os dois limites e a faixa saem do recorte
(curva inteira ou últimos 12 meses) com a queda ruim maior; tirar um de cada
recorte pode inverter os níveis. Já "dias perdendo seguidos" e "dias sem novo
topo" valem o pior recorte **de cada métrica**, que é a regra do bloco 1: são
leituras independentes, não limites que precisam ficar em ordem entre si.

Os limites do dia saem do perfil de execução (camada 4), multiplicados pelos
contratos: `limite_perda_contrato × n` e `max_trades_dia`. Zero significa
desligado no motor — vira `None`, "não definido", e não 0. Contratos zero ou
negativos, sorteio ausente, sorteio sem as quedas guardadas e quedas todas
zeradas viram "não medido" com motivo, nunca limite zero ou negativo.

- [ ] **Passo 1: o teste que falha**

```python
def _leitura(dd95=1000.0, dd50=400.0, seguidas=8.0, submerso=30.0, h=126):
    quedas = np.linspace(0, 2000, 1001)
    return {"boot": {"dd_p95": dd95, "dd_p50": dd50,
                     "perdas_seguidas_p95": seguidas,
                     "submerso_p95": submerso, "horizonte": h,
                     "quedas": quedas},
            "boot_12m": {}}


def test_disjuntor_escala_com_os_contratos():
    """O bootstrap mede 1 contrato. Operando 3, o limite de desligar é 3x —
    senão o disjuntor dispara no primeiro tropeço."""
    d = tamanho.disjuntor(_leitura(), 100_000.0, 3, {})
    assert d["nivel2"]["queda"] == pytest.approx(3000.0)
    assert d["nivel2"]["pct"] == pytest.approx(3.0)
    assert d["nivel1"]["queda"] == pytest.approx(1200.0)


def test_disjuntor_usa_o_pior_dos_dois_recortes():
    """12 meses pior que a curva inteira: vale o pior, como no bloco 1."""
    leitura = _leitura()
    leitura["boot_12m"] = {"dd_p95": 1500.0, "dd_p50": 400.0,
                           "perdas_seguidas_p95": 12.0, "submerso_p95": 40.0,
                           "horizonte": 126, "quedas": np.linspace(0, 3000, 1001)}
    d = tamanho.disjuntor(leitura, 100_000.0, 1, {})
    assert d["nivel2"]["queda"] == pytest.approx(1500.0)
    assert d["nivel1"]["perdas_seguidas"] == 12
    assert d["dias_sem_topo"] == 40


def test_disjuntor_traz_a_chance_de_desligar_a_toa():
    """Metade dos caminhos sorteados passa de 1.000 de queda: desligar em
    1.000 desliga uma estratégia viva metade das vezes."""
    d = tamanho.disjuntor(_leitura(), 100_000.0, 1, {})
    assert d["nivel2"]["risco_de_desligar_pct"] == pytest.approx(50.0, abs=1.0)


def test_limites_do_dia_zerados_no_perfil_viram_nao_definido():
    perfil = {"limite_perda_contrato": 0.0, "max_trades_dia": 0}
    d = tamanho.disjuntor(_leitura(), 100_000.0, 2, perfil)
    assert d["limite_dia_reais"] is None and d["limite_dia_trades"] is None


def test_limites_do_dia_multiplicam_pelos_contratos():
    perfil = {"limite_perda_contrato": 150.0, "max_trades_dia": 3}
    d = tamanho.disjuntor(_leitura(), 100_000.0, 2, perfil)
    assert d["limite_dia_reais"] == pytest.approx(300.0)
    assert d["limite_dia_trades"] == 3


def test_sem_contratos_nao_ha_disjuntor():
    d = tamanho.disjuntor(_leitura(), 100_000.0, 0, {})
    assert d["nivel2"]["queda"] is None and d["motivo"]
```

- [ ] **Passo 2: rodar e ver falhar.**

- [ ] **Passo 3: implementar** (usa `candidata.pior_dos_recortes` e
`candidata.risco_de_desligar` — não reescrever nenhum dos dois).

```python
def disjuntor(leitura: dict, capital: float, n_contratos: int,
              perfil: dict) -> dict:
    from . import candidata

    vazio = {"nivel1": {"queda": None, "perdas_seguidas": None,
                        "acao": "reduzir para 1 contrato"},
             "nivel2": {"queda": None, "pct": None, "acao": "desligar",
                        "risco_de_desligar_pct": None},
             "dias_sem_topo": None, "limite_dia_reais": None,
             "limite_dia_trades": None, "horizonte": None}
    if not n_contratos:
        return {**vazio, "motivo": ("sem número de contratos não há limite "
                                    "de desligamento para calcular")}

    pior = candidata.pior_dos_recortes(leitura)
    boot = leitura.get("boot") or {}
    recorte_dd = pior["dd_p95"]["recorte"]
    b_dd = (leitura.get("boot_12m") if recorte_dd == "últimos 12 meses"
            else boot) or boot

    n = int(n_contratos)
    dd95 = float(pior["dd_p95"]["valor"]) * n
    dd50 = float(b_dd.get("dd_p50") or 0.0) * n
    lim_reais = float((perfil or {}).get("limite_perda_contrato") or 0.0) * n
    trades_dia = int((perfil or {}).get("max_trades_dia") or 0)
    return {
        "nivel1": {"queda": dd50 or None,
                   "perdas_seguidas": int(round(
                       pior["perdas_seguidas_p95"]["valor"])) or None,
                   "acao": "reduzir para 1 contrato"},
        "nivel2": {"queda": dd95, "pct": dd95 / capital * 100 if capital else None,
                   "acao": "desligar e reotimizar",
                   "risco_de_desligar_pct": candidata.risco_de_desligar(
                       b_dd, float(pior["dd_p95"]["valor"]))},
        "dias_sem_topo": int(round(pior["submerso_p95"]["valor"])) or None,
        "limite_dia_reais": lim_reais or None,
        "limite_dia_trades": trades_dia or None,
        "horizonte": int(boot.get("horizonte") or 0) or None,
        "motivo": None,
    }
```

- [ ] **Passo 4: rodar e ver passar.**

- [ ] **Passo 5: provar os testes** — tirar o `× n` do nível 2, ler sempre
  `boot` em vez do pior recorte, e devolver `0` em vez de `None` nos limites do
  dia. Desfazer.

- [ ] **Passo 6: commit**

```bash
git add core/tamanho.py tests/test_tamanho.py
git commit -m "feat(tamanho): disjuntor em dois niveis, escalado pelos contratos e pelo pior recorte"
```

---

## Tarefa 4: a tabela `planos_operacao` e `core/plano.py` ✅ (18/09/2026)

**Arquivos:**
- Modificar: `core/schema.sql`, `core/wfa_store.py`, `core/optimizer.py`
- Criar: `core/plano.py`
- Testar: `tests/test_plano.py` — 9 testes, 8 mutações provadas

**Interfaces produzidas:**
```python
plano.salvar(**campos) -> int          # devolve plano_id
plano.listar(wfa_id=None, apenas_ativos=False) -> list[dict]
plano.detalhes(plano_id) -> dict | None
plano.excluir(plano_id) -> bool
plano.aposentar(plano_id) -> bool      # estado 'ativo' -> 'aposentado'
```
Campos de `salvar`: `wfa_id`, `run_id`, `symbol`, `strategy`, `nome`,
`params`, `profile`, `capital`, `contratos`, `risco_pedido_pct`,
`risco_efetivo_pct`, `perda_referencia`, `de_onde`, `margem`,
`uso_margem_pct`, `camada4_travada`, `disjuntor`, `expectativa`,
`reotimizacao`, `definicoes`, `regua`.

A tabela nasce sozinha na subida do app (`init_schema`, com `CREATE TABLE IF
NOT EXISTS`) — banco existente não precisa de migração à mão.

### As decisões

- **Retrato, nunca referência**: `params`, `profile`, `capital` e os limiares
  vão copiados para dentro do plano. Mineração apagada não pode derrubar o
  dimensionamento de uma estratégia que está operando.
- **Sem `UNIQUE` por `wfa_id`**: dois planos do mesmo walk-forward com risco
  diferente são duas decisões, e ambas são histórico.
- **Cascata nos três pontos** (`wfa_store.excluir`, `optimizer.excluir_salva`,
  o botão da tela). O acidente de deixar 551 trades órfãos já aconteceu uma vez.
- Plano não se edita: **aposenta-se** e grava-se outro. Histórico de decisão
  reescrito não é histórico.

- [ ] **Passo 1: o teste que falha**

```python
# tests/test_plano.py  (banco temporário — nunca data/database.duckdb)
def test_salvar_e_ler_devolve_os_retratos(tmp_db):
    pid = plano.salvar(
        wfa_id=1, run_id=2, symbol="WIN$N", strategy="rompimento_canal",
        nome="teste", params={"periodo_canal": 78}, profile={"contratos": 1},
        capital=100_000.0, contratos=3, risco_pedido_pct=1.0,
        risco_efetivo_pct=0.9, perda_referencia=300.0,
        de_onde="a média dos 5% piores pregões", margem=None,
        disjuntor={"nivel2": {"queda": 3000.0}}, expectativa={"p50_6m": 5000.0},
        reotimizacao={"is_meses": 18, "camada4_travada": True},
        regua={"holdout": "R$ 942"}, camada4_travada=True)
    d = plano.detalhes(pid)
    assert d["params"] == {"periodo_canal": 78}
    assert d["contratos"] == 3 and d["estado"] == "ativo"


def test_dois_planos_do_mesmo_wfa_convivem(tmp_db):
    """Risco diferente é decisão diferente, não correção da anterior."""
    a = plano.salvar(wfa_id=1, contratos=3, risco_pedido_pct=1.0, ...)
    b = plano.salvar(wfa_id=1, contratos=1, risco_pedido_pct=0.5, ...)
    assert {p["plano_id"] for p in plano.listar(wfa_id=1)} == {a, b}


def test_excluir_walk_forward_leva_os_planos_junto(tmp_db):
    pid = plano.salvar(wfa_id=1, ...)
    wfa_store.excluir(1)
    assert plano.detalhes(pid) is None


def test_excluir_mineracao_leva_planos_dos_seus_walk_forwards(tmp_db):
    """Apagar mineração apaga WFA e plano: é a regra que o usuário travou."""
    ...
    optimizer.excluir_salva(run_id)
    assert plano.listar() == []


def test_aposentar_nao_apaga(tmp_db):
    pid = plano.salvar(wfa_id=1, ...)
    plano.aposentar(pid)
    assert plano.detalhes(pid)["estado"] == "aposentado"
```

(o executor completa os `...` com os mesmos campos do primeiro teste — o
importante é que cada teste prove **uma** regra)

- [ ] **Passo 2: rodar e ver falhar.**

- [ ] **Passo 3: schema + módulo**

```sql
-- O passo 10 fecha aqui: o plano é o que a incubação vai ler e o que a
-- operação vai obedecer. Retratos, não referências: mineração apagada não
-- pode mudar o tamanho de posição de quem já está operando.
CREATE TABLE IF NOT EXISTS planos_operacao (
    plano_id        BIGINT PRIMARY KEY,
    wfa_id          BIGINT,
    run_id          BIGINT,
    symbol          VARCHAR,
    strategy        VARCHAR,
    nome            VARCHAR,
    created_at      TIMESTAMP,
    params          JSON,     -- retrato
    profile         JSON,     -- retrato
    capital         DOUBLE,
    contratos       INTEGER,
    risco_pedido_pct    DOUBLE,
    risco_efetivo_pct   DOUBLE,
    perda_referencia    DOUBLE,
    de_onde         VARCHAR,  -- qual das três leituras dimensionou
    margem          DOUBLE,
    disjuntor       JSON,
    expectativa     JSON,
    reotimizacao    JSON,
    regua           JSON,     -- limiares congelados + resultado do holdout
    camada4_travada BOOLEAN,
    estado          VARCHAR   -- 'ativo' | 'aposentado'
);
CREATE SEQUENCE IF NOT EXISTS seq_plano_id START 1;
```

`core/plano.py` segue o formato de `core/wfa_store.py` (mesmo `connect_write`,
mesma `transacao`, mesmo `json.dumps` nos campos JSON).

Cascata: em `wfa_store.excluir`, antes de apagar `wfa_runs`,
`DELETE FROM planos_operacao WHERE wfa_id = ?`; em `optimizer.excluir_salva`,
`DELETE FROM planos_operacao WHERE wfa_id IN (SELECT wfa_id FROM wfa_runs WHERE run_id = ?)`
**antes** de apagar os walk-forwards.

- [ ] **Passo 4: rodar e ver passar.**

- [ ] **Passo 5: provar os testes** — tirar a linha da cascata de
  `optimizer.excluir_salva` e ver o teste da mineração falhar; desfazer.

- [ ] **Passo 6: commit**

```bash
git add core/schema.sql core/plano.py core/wfa_store.py core/optimizer.py tests/test_plano.py
git commit -m "feat(plano): tabela planos_operacao com retratos e cascata nos tres pontos"
```

---

## Tarefa 5: camada 4 travada no walk-forward ✅ (18/09/2026)

**Arquivos:**
- Modificar: `core/wfa.py:748` (`rodar`), `core/wfa.py:1014` (`matrizes`),
  `core/wfa_store.py` (coluna nova), `core/schema.sql`,
  `ui/components/wfa_panel.py` (a caixa), `ui/callbacks.py:1304` e `:1405`
- Testar: `tests/test_wfa_camada4.py`, `tests/test_callbacks_sem_ciclo.py`

**Interfaces produzidas:**
```python
wfa.rodar(..., travar_execucao: set[str] | None = None)
wfa.matrizes(..., travar_execucao: set[str] | None = None)
```

### A regra, por escrito

Com `travar_execucao` preenchido (os nomes de `wfa_runner.CAMPOS_EXECUCAO_NOMES`):

1. a **primeira janela real** escolhe normalmente, entre todos os aprovados;
2. os valores que ela escolheu para esses campos ficam **travados**;
3. nas janelas seguintes, só continuam candidatas as combinações que casam
   com esses valores;
4. se nenhuma aprovada casar, a janela fica **fora do mercado** — a mesma
   regra que o WFA já aplica quando ninguém passa nos critérios.

Travar no valor da primeira janela, e não no melhor do período inteiro, é o
que impede olhar o futuro. Comparação de valor usa `candidata.chave`/`_valor`
(78.0 e 78 são o mesmo ponto), não `==` de dicionário.

- [ ] **Passo 1: o teste que falha**

```python
def test_travada_a_segunda_janela_nao_troca_o_stop():
    """Duas combinações, stop 300 e stop 500. A primeira janela escolhe a de
    stop 300; na segunda, a de stop 500 é a melhor — e mesmo assim não pode
    ser escolhida. Sem trava, ela seria."""
    ...
    passos = wfa.rodar(combos, janelas, capital, travar_execucao={"stop_pontos"})
    assert [p.params["stop_pontos"] for p in passos] == [300, 300]
    livres = wfa.rodar(combos, janelas, capital)
    assert [p.params["stop_pontos"] for p in livres] == [300, 500]


def test_travada_sem_candidata_que_case_fica_fora_do_mercado():
    """Regra herdada do WFA: sem combinação válida, não se opera."""
    ...
    assert passos[1].fora_do_mercado is True


def test_trava_compara_78_com_78_ponto_zero():
    """Float do JSON contra int do banco: sem normalizar, a trava não acha
    nenhuma candidata e o WFA inteiro fica fora do mercado em silêncio."""
    ...
```

- [ ] **Passo 2: rodar e ver falhar.**

- [ ] **Passo 3: implementar** em `rodar`: depois de `escolher` na primeira
janela real, guardar `travados = {k: _valor(params[i][k]) for k in travar_execucao}`;
nas seguintes, filtrar `aprovados` por esses valores antes de `escolher`; lista
vazia → `Passo(fora_do_mercado=True)`. `matrizes` repassa o argumento.

- [ ] **Passo 4: rodar e ver passar**, mais a suíte inteira do WFA
(`python -m pytest tests/test_wfa*.py -q`) — este é o ponto do plano com maior
chance de quebrar coisa antiga.

- [ ] **Passo 5: a caixa na tela**

Uma caixa de marcar no painel do Walk-Forward: **"travar stop, alvo e
proteções (reotimizar só a estratégia)"**, nascendo **marcada**, com (?):
"Marcado, a primeira janela escolhe o stop, o alvo e as proteções e todas as
seguintes ficam com eles, reotimizando só os parâmetros da estratégia. Esses
campos protegem o capital, não geram lucro: reotimizá-los faz o stop aprender o
passado, e muda o disjuntor do plano a cada seis meses. Desmarque só se quiser
medir o efeito de reotimizar tudo."

Grava em `wfa_runs.camada4_travada` (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`),
`wfa_store.salvar` recebe e `detalhes` devolve. Rodar
`python -m pytest tests/test_callbacks_sem_ciclo.py -q`.

### Como ficou

`wfa.rodar(..., travar_execucao)` e `wfa.matriz/matrizes(..., travar_execucao)`.
A caixa **"travar stop, alvo e proteções"** fica ao lado de "estender ao
holdout", nasce marcada, entra na chave do cache da matriz (com e sem trava são
duas matrizes diferentes) e é gravada em `wfa_runs.camada4_travada`. Carregar um
walk-forward salvo devolve a caixa ao estado dele; registro anterior à coluna
volta marcado, que é o padrão de hoje.

Detalhe que quase passou: quando a trava filtra os aprovados, o `memo` da
janela precisa ser descartado — ele guarda a escolha de cada inteligência sobre
os aprovados **antigos**, e reaproveitá-lo devolveria justamente a combinação
que a trava acabou de excluir.

**A matriz e as sete inteligências usam os valores travados da configuração
aberta**, não os que cada uma aprenderia da própria primeira janela: sete
inteligências × doze configurações travariam em até doze stops diferentes, e a
matriz passaria a misturar "de que tamanho de janela a estratégia precisa" com
"que stop aquela célula calhou de pegar". Por isso `rodar` aceita também
`valores_travados`, prontos, além de `travar_execucao`, que os aprende.

A chave do cache da matriz passou a ter **um dono só** (`_chave_matriz`): quem
guardava e quem lia montavam a string cada um por conta própria, e bastou a
camada 4 entrar de um lado para o outro nunca mais achar nada — `sharpes_matriz`
gravava vazio em todo walk-forward salvo, sem erro aparecer. Os valores travados
entram na chave, porque trocar de inteligência pode travar noutro stop.

11 testes em `tests/test_wfa_camada4.py`, mais a suíte inteira (668).

---

## Tarefa 6: o bloco 5 na tela ✅ (18/09/2026)

**Arquivos:**
- Modificar: `ui/components/candidata_panel.py`, `ui/callbacks_candidata.py`
- Testar: `tests/test_candidata_tabela.py`, `tests/test_callbacks_candidata.py`,
  `tests/test_callbacks_sem_ciclo.py`

**Interfaces produzidas:**
```python
CP.bloco_tamanho(dim: dict, disj: dict, capital: float) -> html.Div
CP.linhas_tamanho(dim, disj, capital) -> list[tuple[str, str, list[dict]]]
```

### O que aparece

Duas entradas acima da tabela: **risco por trade (%)**, padrão 1,0; e
**margem por contrato (R$)**, vazia por padrão ("não informada").

Tabela com mapa de calor, dois grupos:

| grupo | linhas |
|---|---|
| Quanto operar | contratos · risco pedido × risco efetivo · perda de referência (e de onde veio) · o que limitou (risco ou margem) |
| Quando parar | reduzir para 1 contrato em (R$ e %) · desligar em (R$ e %) · chance de desligar à toa · dias perdendo seguidos · dias sem novo topo · limite do dia (R$ e trades) |

Regras de tom: risco efetivo acima do pedido nunca acontece (é piso); `n = 0`
pinta vermelho com o motivo; chance de desligar à toa acima de 10% pinta
vermelho (o disjuntor desliga estratégia viva demais); margem não informada
pinta neutro com a nota "não conferida".

Cada (?) diz o que é, o que é bom e o que é ruim. O (?) de "perda de
referência" explica que o CVaR é a **média** da cauda, não o teto: metade das
perdas da cauda será maior.

Botão **Gravar plano de operação**, desligado enquanto:
- o veredito não estiver aprovado (com ou sem ressalva);
- `n == 0`;
- os testes demorados não tiverem rodado (portão pendente aprova nada).

O botão avisa qual dos três motivos está travando, em vez de só aparecer
apagado.

- [ ] **Passo 1: testes que falham** — `linhas_tamanho` devolve os dois grupos
com os nomes e tons certos; `n = 0` aparece com o motivo; margem não informada
não vira zero; o botão fica desligado nos três casos e ligado quando nenhum
deles vale.

- [ ] **Passo 2: rodar e ver falhar.**

- [ ] **Passo 3: implementar** reusando `_tabela` e `_tom`; **nenhum cartão
novo**.

- [ ] **Passo 4: rodar e ver passar**, incluindo
`tests/test_callbacks_sem_ciclo.py`.

- [ ] **Passo 5: ver na tela** — subir o app, abrir o modo Candidata no
walk-forward #8, conferir contratos, disjuntor e os (?) — e só então marcar
como pronto.

### Como ficou

`CP.linhas_tamanho(dim, ref, disj, capital)` e `CP.bloco_tamanho(...)`, com os
mesmos dois grupos do desenho, e `CP.entradas_tamanho()` com os três diais lado
a lado: risco por pregão (%), garantia por contrato (R$) e capital para
garantia (%). O callback `cand_tamanho` é separado do dos portões de propósito
— mexer no risco não pode disparar de novo os 2.000 caminhos do holdout, e
tamanho não muda veredito.

**Com zero contratos a tabela não fica vazia.** Os limites aparecem calculados
para 1 contrato, com a nota "conta feita com 1 contrato, que é mais do que o
seu risco por pregão permite hoje". Esconder número medido de quem acabou de
descobrir que o capital não comporta o instrumento seria o pior momento
possível para esconder.

Conferido na tela com o walk-forward #8 (capital R$ 10.000): a 1% por pregão dá
**0 contratos** com o motivo escrito na linha; a 5% dá **1 contrato**, risco
real 4,26%, e o aviso some.

**A leitura de robustez é guardada por walk-forward** (`leitura_do_wfa`): são
2.000 caminhos sorteados duas vezes, ~0,35 s, e sem guardar cada mexida no dial
de risco refazia tudo — arrastar 1% para 2% custava quase quatro segundos de
conta repetida, além de ler os trades do banco duas vezes por clique. Não cabe
num `dcc.Store`: a leitura carrega arrays do numpy que não viram JSON.

**O aviso de "1 contrato" vale para as quatro linhas** que são multiplicadas
pelo número de contratos (os dois níveis, o pior lucro do prazo e o limite do
dia), vem **na frente** da nota (na coluna estreita, o fim é o que some
primeiro) e cita **a conta que realmente zerou** — mandar mexer no risco quando
quem travou foi a garantia é o defeito que o motivo da linha "contratos"
existe para evitar.

Os textos passaram por uma régua nova, travada em teste: nenhuma explicação usa
"cauda", "ciclos", "caminhos simulados", "percentil", "CVaR", "drawdown" ou
"bootstrap" — nem nos (?) nem nas notas — e **toda** linha diz o que é bom e o
que é ruim, não só o que o número significa.

18 testes em `tests/test_candidata_tabela.py` e 8 em
`tests/test_callbacks_candidata.py` (inclusive `_dimensionar`, que existia sem
teste nenhum). Suíte inteira: 693.

---

## Tarefa 7: gravar o plano pela tela ✅ (19/09/2026)

**Arquivos:**
- Modificar: `ui/callbacks_candidata.py`, `ui/components/candidata_panel.py`
- Testar: `tests/test_callbacks_candidata.py`

O botão monta o plano com os **seis grupos** do desenho (§4.5): identidade,
retratos, tamanho, disjuntor, definições, expectativa, reotimização e régua.

**As definições vão escritas dentro do plano**, não subentendidas: o que conta
como novo topo, se a queda é medida sobre o capital inicial ou o corrente, se
posição aberta conta, qual a regra de reentrada depois de reduzir, e a receita
da reotimização (qual mineração, qual inteligência, IS de quantos meses,
critérios de aceite, **camada 4 travada**, e o que fazer se nenhuma combinação
passar — ficar fora do mercado).

Duas regras operacionais gravadas junto, em texto:
- **reotimizar imediatamente antes de ligar**, com dado até a véspera;
- **nunca trocar parâmetro com posição aberta**: reotimiza fora do pregão, vale
  a partir da abertura seguinte.

Depois de gravar, a tela mostra o plano gravado com data e o botão vira
"Gravar outro plano" — plano não se edita.

- [ ] **Passo 1: teste que falha** — clicar grava uma linha com os retratos
  certos; clicar duas vezes grava dois planos (não sobrescreve); com veredito
  reprovado, não grava nada.
- [ ] **Passo 2: rodar e ver falhar.**
- [ ] **Passo 3: implementar.**
- [ ] **Passo 4: rodar e ver passar** + `test_callbacks_sem_ciclo.py`.
- [ ] **Passo 5: gravar um plano de verdade no #8 e conferir no banco.**
- [ ] **Passo 6: commit.**

### Como ficou

`core/plano.py` ganhou `pode_gravar` (o motivo do bloqueio em palavras),
`expectativa` (faixa do pior ao melhor décimo em 3, 6 e 12 meses — sorteio
próprio de 12 meses, porque o da tela vai só até a reotimização) e `montar`
(todos os campos de `salvar` a partir do que a tela já calculou; não recalcula
nada, o plano grava o que o operador viu). O JSON passou a aceitar número do
numpy — sem isso o clique quebrava justamente no plano mais completo.

Na tela, o selo publica o veredito num `dcc.Store`, e o botão lê dali: mexer
no dial não refaz os 2.000 caminhos do holdout. O botão nasce desligado e o
motivo fica escrito ao lado — reprovada (com os portões que reprovaram),
testes completos não rodados, ou zero contratos (com a conta que zerou). A
trava é conferida **de novo no servidor** ao gravar: botão desligado no
navegador não é garantia de nada. Depois de gravar, o rótulo vira "Gravar
outro plano".

Conferido na tela com o #8: sem os testes completos, travado com o motivo
certo; depois deles (aprovada com ressalva, 11/12), travado pelo segundo
motivo, zero contratos a 1%; a 5% cabe 1 contrato e o botão libera. A
gravação em si foi provada com banco temporário, para não deixar plano de
teste no banco real.

21 testes em `test_plano.py`, 5 novos em `test_callbacks_candidata.py`, 6
mutações provadas. Suíte inteira: 720.

---

## Tarefa 8: as seis dívidas da etapa 2

Uma por vez, cada uma com seu teste e seu commit:

- [ ] a barra diz "testes completos" mesmo quando uma fase falhou — precisa
  dizer qual falhou;
- [ ] o nome do segundo portão do platô muda conforme o caminho do dado;
- [ ] (?) com "2 passos" escrito na mão, em vez de vir de `passos_min`;
- [ ] `_fmt_portao` preso a nomes exatos de portão — quebra ao renomear;
- [ ] portão do capital com as duas simulações vazias precisa cair em "não
  medido", não em número;
- [ ] `tick_value` chega ao portão de custo sem teste de regressão que prove
  que o caminho inteiro (YAML → portão) funciona.

```bash
git commit -m "fix(candidata): dividas da etapa 2"
```

---

## Tarefa 9: rodar de verdade e documentar

- [ ] Rodar a tela inteira no walk-forward **#8** (o de referência) e registrar
  no doc: contratos, risco efetivo, os dois níveis do disjuntor e a chance de
  desligar à toa. Repetir no **#10** e no **#11** para ter três casos.
- [ ] `docs/CALCULOS-CANDIDATA.md`: seção nova com esses números reais e as
  contas em linguagem simples.
- [ ] `docs/PLANO-CANDIDATA.md`: fase 5 e 6 marcadas, decisão da camada 4
  travada registrada com a data.
- [ ] `docs/PLANO-WFA.md`: tarefa 5.6 marcada como feita.
- [ ] `docs/METODOLOGIA.md`, `README.md`, `CHANGELOG.md`.
- [ ] Revisão final da branch inteira por agente, uma onda de correções.

```bash
git commit -m "docs(candidata): etapa 3 medida em tres walk-forwards reais"
```

---

## Conferência do plano contra o desenho

| desenho | tarefa |
|---|---|
| §4.5 CVaR do pregão, piso de estresse, margem | 1, 2 |
| §4.5 `contratos = 0` reprova | 2 |
| §4.5 risco efetivo do inteiro | 2 |
| §4.5 plano de operação, seis grupos | 4, 7 |
| §4.5 sem `UNIQUE`, cascata nos três pontos | 4 |
| §6.3 desligar em degraus | 3, 6 |
| §6.4 receita da reotimização e as duas regras | 7 |
| §6.4 tarefa 5.6 do PLANO-WFA | 5 |
| §7 tela: tabela, (?), botão travado com motivo | 6, 7 |
| §8 fase 5.1, 5.2, 5.3 | 2, 4, 5 |
| dívidas da etapa 2 | 8 |
| medir antes de afirmar (6.1 da etapa 2) | 9 |
