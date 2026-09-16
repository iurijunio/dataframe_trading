# Modo Candidata — plano de execução, etapa 2 (aprovar ou reprovar)

> **Para quem executa:** implemente tarefa por tarefa, na ordem. Cada passo é
> uma ação curta. Não pule o passo de ver o teste **falhar**. Toda conta que
> decide aprovação precisa de teste que falhe quando a implementação é
> quebrada de propósito — prove isso no relatório.

**Objetivo:** a tela Candidata passa a dizer **APROVADA** ou **REPROVADA**,
com os oito portões e os três alertas da tabela "Os portões da etapa 2" em
[PLANO-CANDIDATA.md](PLANO-CANDIDATA.md) (seção "Decisões revistas em
16/09/2026"). Essa tabela manda; onde este plano divergir dela, ela vence.

**Arquitetura:** contas puras em `core/candidata.py` (portões) e `core/spa.py`
(teste de muitas tentativas); o teste de entrada aleatória janela a janela
em `core/aleatorio.py`; os testes demorados rodam em segundo plano em
`core/candidata_runner.py`; a faixa de veredito na tela reaproveita o selo
do Walk-Forward.

**Ferramentas:** Python 3.11, numpy, DuckDB, Dash 4.4.1, Numba, pytest.
**Sem scipy.** Python do projeto: `.venv/Scripts/python.exe`.

## Restrições globais

- Código, nomes e comentários em **português**. Comentário explica **por quê**.
- **Textos de tela em português simples**: o nome do portão é a pergunta que
  ele responde ("O lucro não depende de poucos dias?"), e o (?) explica sem
  sigla nem jargão. Termo técnico, se inevitável, uma vez e entre parênteses.
- Nada em `core/` importa Dash.
- Nenhum teste toca o banco real `data/database.duckdb`.
- Todo portão devolve o mesmo formato:
  `{"nome", "ok", "critico", "valor", "exigido", "dica"}` — o de
  `core/wfa.py::_portao_wfa`. `ok` pode ser `None` = **ainda não medido**.
- Suíte hoje: **460 testes verdes**. Rode a suíte inteira antes de cada commit.
- `tests/test_callbacks_sem_ciclo.py` passa inteiro depois de qualquer
  mudança em callback.
- Commit: `git -c user.name="Dataframe" -c user.email="iurijunio5@gmail.com" commit`.

## O que já existe e deve ser reaproveitado

| peça | onde |
|---|---|
| perfil do platô, com `borda_esq/borda_dir` | `core/candidata.py::perfil_plato` |
| série por pregão com dias parados valendo zero | `core/candidata.py::por_pregao` |
| leitura de robustez (pior dos dois recortes) | `core/candidata.py::leitura_robustez`, `pior_dos_recortes` |
| bootstrap em blocos, com horizonte | `core/robustez.py::bootstrap`, `bloco_medio` |
| entrada aleatória, calibração, p-valor | `core/aleatorio.py` |
| varredura da mineração (todas as combinações) | `core/wfa_runner.py::VARREDURA` |
| curvas das combinações fixas e percentil | `core/wfa.py::faixa_fixas`, `percentil_na_faixa` |
| formato e veredito dos portões | `core/wfa.py::_portao_wfa`, `portoes_wfa` |
| desenho do selo com a lista de portões | `ui/components/wfa_panel.py::selo` |
| data do corte do holdout | `optimizer.detalhes_salva(run_id)["holdout_de"]` |
| valor do tick | `configs/instruments/*.yaml`, campo `tick_value` |

---

### Tarefa 1: Portão do platô e alerta de vizinho com prejuízo

Hoje `perfil_plato` sabe se a caminhada parou por queda ou porque a grade
acabou, mas um ponto **não minerado** ao lado do centro é lido como queda.
Nenhum dos dois casos de falta de medição pode reprovar.

**Arquivos:** `core/candidata.py`, `tests/test_candidata.py`.

**Interfaces produzidas:**
- `perfil_plato` ganha as chaves `parada_esq` e `parada_dir`, cada uma
  `"queda" | "borda" | "buraco"` (ou `None` quando se abstém). `borda_esq` e
  `borda_dir` continuam existindo (`parada == "borda"`). Atualize o teste de
  contrato de chaves.
- `portao(nome, ok, critico, valor, exigido, dica) -> dict`.
- `portoes_plato(perfil: dict, passos_min: int = 2) -> list[dict]` — devolve
  **dois** portões: o crítico e o alerta.
- `alerta_vizinho(perfil: dict, raio: int = 2) -> dict`.

- [ ] **Passo 1: testes que falham**

```python
def _perfil_com(fr, deploy_idx, ausentes=()):
    valores = list(range(40, 40 + len(fr)))
    trials = [{"params": {"p": v}, "lucro": f * 100.0, "dd": 100.0}
              for i, (v, f) in enumerate(zip(valores, fr)) if i not in ausentes]
    return candidata.perfil_plato(trials, {"p": valores},
                                  {"p": float(valores[deploy_idx])})


def test_parada_distingue_queda_borda_e_buraco():
    p = _perfil_com([1, 5, 5, 5, 5], deploy_idx=3, ausentes=(1,))
    assert p["parada_dir"] == "borda"
    assert p["parada_esq"] == "buraco"
    q = _perfil_com([5, 1, 5, 5, 5, 5], deploy_idx=3)
    assert q["parada_esq"] == "queda"


def test_plato_reprova_so_por_queda_real():
    """Queda a um passo do centro reprova. Fim da faixa testada e ponto não
    minerado não reprovam — viram alerta."""
    queda = candidata.portoes_plato(_perfil_com([5, 1, 5, 5, 5, 5], 3))
    assert queda[0]["critico"] and queda[0]["ok"] is False
    borda = candidata.portoes_plato(_perfil_com([5, 5, 5, 5, 5], 3))
    assert borda[0]["ok"] is True
    assert borda[1]["critico"] is False and borda[1]["ok"] is False


def test_plato_largo_dos_dois_lados_passa_sem_alerta():
    p = candidata.portoes_plato(_perfil_com([5] * 9, 4))
    assert p[0]["ok"] is True and p[1]["ok"] is True


def test_alerta_vizinho_com_prejuizo():
    p = _perfil_com([5, 5, 5, -1, 5, 5, 5], 4)
    assert candidata.alerta_vizinho(p)["ok"] is False
    assert candidata.alerta_vizinho(_perfil_com([5] * 7, 3))["ok"] is True
```

- [ ] **Passo 2:** rodar e ver falhar.

- [ ] **Passo 3: implementação.** Em `perfil_plato`, a função interna `anda`
passa a devolver `(n, motivo)`: `"borda"` quando o índice sai da grade,
`"buraco"` quando o ponto seguinte tem `fr is None`, `"queda"` quando o
ponto seguinte está abaixo do piso. Acrescente `parada_esq` e `parada_dir` ao
`_perfil` (todas as saídas continuam com o mesmo conjunto de chaves).

```python
def portao(nome, ok, critico, valor, exigido, dica) -> dict:
    return {"nome": nome, "ok": ok, "critico": critico, "valor": valor,
            "exigido": exigido, "dica": dica}


def portoes_plato(perfil: dict, passos_min: int = 2) -> list[dict]:
    """A região do parâmetro é larga? Só reprova com queda de verdade perto
    do centro: faixa testada que acaba ou ponto não minerado são falta de
    medição, e falta de medição vira alerta, não reprovação."""
    nome = "O parâmetro está numa região larga?"
    dica = ("Mede quantos valores vizinhos do parâmetro escolhido, para cada "
            "lado, continuam dando pelo menos 60% do resultado dele (lucro "
            "dividido pela maior queda). Precisa de pelo menos 2 de cada "
            "lado: um parâmetro que só funciona num valor exato é sorte, não "
            "estratégia.")
    if perfil.get("abstem"):
        return [portao(nome, True, True, "não medido", f"≥ {passos_min} por lado", dica),
                portao("A região foi medida por inteiro?", False, False,
                       perfil.get("motivo") or "não foi possível medir", "medida",
                       "Sem dados suficientes da mineração para medir a região.")]
    lados = [(perfil["largura_esq"], perfil["parada_esq"]),
             (perfil["largura_dir"], perfil["parada_dir"])]
    queda = any(n < passos_min and m == "queda" for n, m in lados)
    faltou = [m for n, m in lados if n < passos_min and m != "queda"]
    valor = f"{perfil['largura_esq']} à esquerda · {perfil['largura_dir']} à direita"
    critico = portao(nome, not queda, True, valor, f"≥ {passos_min} por lado", dica)
    alerta = portao(
        "A faixa testada cobre a região?", not faltou, False,
        ("termina perto do parâmetro" if "borda" in faltou
         else "há valores não minerados perto" if faltou else "sim"),
        "cobre",
        "Quando a faixa minerada termina (ou tem buracos) a menos de 2 passos "
        "do parâmetro escolhido, não dá para saber se a região continua boa "
        "daquele lado. Amplie a mineração para confirmar.")
    return [critico, alerta]


def alerta_vizinho(perfil: dict, raio: int = 2) -> dict:
    """Algum valor a até `raio` passos do escolhido dá prejuízo?"""
    pontos = perfil.get("pontos") or []
    i = next((k for k, p in enumerate(pontos) if p.get("atual")), None)
    ruins = [] if i is None else [
        p for p in pontos[max(0, i - raio): i + raio + 1]
        if p.get("lucro") is not None and p["lucro"] < 0]
    return portao(
        "Algum vizinho dá prejuízo?", not ruins, False,
        f"{len(ruins)} com prejuízo" if ruins else "nenhum", "nenhum",
        "Valores do parâmetro a até 2 passos do escolhido que deram prejuízo "
        "na mineração. Um vizinho no vermelho não reprova, mas diz que um "
        "pequeno erro de ajuste já custa dinheiro.")
```

- [ ] **Passo 4:** rodar, ver passar; **provar discriminação** trocando
`"buraco"` por `"queda"` na caminhada (o teste de parada tem que falhar) e
fazendo `queda` sempre `False` (o teste de reprovação tem que falhar).
Suíte inteira, commit `feat(candidata): portão do platô e alerta de vizinho`.

---

### Tarefa 2: Portões que saem dos dados salvos

**Arquivos:** `core/candidata.py`, `tests/test_candidata.py`.

**Interfaces produzidas:**
- `t_diario(pnl: np.ndarray) -> float`
- `portao_acaso(pnl, minimo=2.0) -> dict` (portão 3)
- `portao_poucos_dias(pnl, quantos=5) -> dict` (portão 4)
- `portao_custo(lucro_liquido, contratos, tick_value) -> dict` (portão 5)
- `portao_capital(perda_esperada, contratos_por_trade, capital, teto_pct=20.0) -> dict` (portão 7)
- `alerta_poucos_trades(liquido, fracao=0.01) -> dict`
- `veredito(portoes: list[dict]) -> dict` com `estado`, `cor`, `n_ok`,
  `n_portoes`, `reprovados`, `ressalvas`, `pendentes`, `portoes`.

- [ ] **Passo 1: testes que falham**

```python
def test_t_diario_conta_os_dias_parados():
    """Dias sem trade entram como zero: sem eles quem opera pouco parece firme."""
    so_operados = np.array([10.0, 12.0, 9.0, 11.0])
    com_parados = np.concatenate([so_operados, np.zeros(40)])
    assert candidata.t_diario(com_parados) < candidata.t_diario(so_operados)


def test_portao_acaso():
    firme = np.full(250, 10.0) + np.random.default_rng(1).normal(0, 5, 250)
    ruido = np.random.default_rng(2).normal(0, 50, 250)
    assert candidata.portao_acaso(firme)["ok"] is True
    assert candidata.portao_acaso(ruido)["ok"] is False


def test_portao_poucos_dias():
    """Lucro que vive de 5 dias bons não é um sistema."""
    dependente = np.array([-2.0] * 100 + [60.0] * 5)
    espalhado = np.array([3.0] * 100 + [10.0] * 5)
    assert candidata.portao_poucos_dias(dependente)["ok"] is False
    assert candidata.portao_poucos_dias(espalhado)["ok"] is True


def test_portao_custo_um_tick_por_ponta():
    """510 trades de 1 contrato, 1 tick = R$ 1: custo extra R$ 1.020."""
    contratos = np.ones(510)
    assert candidata.portao_custo(1500.0, contratos, 1.0)["ok"] is True
    assert candidata.portao_custo(1000.0, contratos, 1.0)["ok"] is False


def test_portao_capital_por_contrato():
    """Perda de R$ 3.000 operando 2 contratos = R$ 1.500 por contrato."""
    assert candidata.portao_capital(3000.0, 2.0, 10_000.0)["ok"] is True
    assert candidata.portao_capital(3000.0, 1.0, 10_000.0)["ok"] is False


def test_veredito_pendente_nao_aprova():
    ok = candidata.portao("a", True, True, 1, "", "")
    pend = candidata.portao("b", None, True, None, "", "")
    alerta = candidata.portao("c", False, False, 1, "", "")
    reprova = candidata.portao("d", False, True, 1, "", "")
    assert candidata.veredito([ok, pend])["estado"] == "aguardando testes completos"
    assert candidata.veredito([ok, pend, reprova])["estado"] == "reprovada"
    assert candidata.veredito([ok, alerta])["estado"] == "aprovada com ressalva"
    assert candidata.veredito([ok])["estado"] == "aprovada"
```

- [ ] **Passo 2:** rodar e ver falhar.

- [ ] **Passo 3: implementação**

```python
def t_diario(pnl: np.ndarray) -> float:
    """Média diária dividida pelo seu erro, contando os dias parados. É o
    teste do resultado por DIA, e não por trade: trades do mesmo pregão
    andam juntos, e contá-los como independentes infla a firmeza."""
    x = np.asarray(pnl, dtype=float)
    if len(x) < 30:
        return 0.0
    desvio = float(x.std(ddof=1))
    return float(x.mean() / (desvio / np.sqrt(len(x)))) if desvio > 0 else 0.0


def portao_acaso(pnl, minimo: float = 2.0) -> dict:
    t = t_diario(pnl)
    return portao(
        "O lucro não é acaso?", t >= minimo, True, round(t, 2), f"≥ {minimo:.1f}",
        "Compara o ganho médio por dia com o quanto o resultado diário oscila. "
        "Abaixo de 2, a média ainda pode ser zero e o lucro visto ser sorte. "
        "Conta os dias parados como zero.")


def portao_poucos_dias(pnl, quantos: int = 5) -> dict:
    x = np.asarray(pnl, dtype=float)
    sobra = float(x.sum() - np.sort(x)[::-1][:quantos].sum())
    return portao(
        "O lucro não depende de poucos dias?", sobra > 0, True, round(sobra, 2),
        f"> 0 sem os {quantos} melhores",
        f"O lucro total tirando os {quantos} melhores dias. Se ficar negativo, "
        "a estratégia viveu de alguns dias de sorte — que podem não se repetir.")


def portao_custo(lucro_liquido: float, contratos, tick_value: float) -> dict:
    extra = 2.0 * float(np.sum(contratos)) * tick_value
    sobra = float(lucro_liquido - extra)
    return portao(
        "Aguenta custo maior?", sobra > 0, True, round(sobra, 2),
        "> 0 com +1 tick por ponta",
        "O lucro depois de pagar 1 tick a mais na entrada e na saída de cada "
        "trade. No mini índice 1 tick vale mais que a corretagem inteira, e "
        "ordem a mercado na hora da pressa costuma escorregar isso. Se o lucro "
        "some, a estratégia vive no limite do custo.")


def portao_capital(perda_esperada: float, contratos_por_trade: float,
                   capital: float, teto_pct: float = 20.0) -> dict:
    por_contrato = perda_esperada / max(float(contratos_por_trade), 1.0)
    pct_ = por_contrato / capital * 100 if capital else float("inf")
    return portao(
        "O capital comporta 1 contrato?", pct_ <= teto_pct, True,
        round(pct_, 1), f"≤ {teto_pct:.0f}% do capital",
        "A perda esperada operando só 1 contrato, em % do capital. Se nem o "
        "mínimo cabe, não é a estratégia que está errada — é o capital que não "
        "comporta o instrumento.")


def alerta_poucos_trades(liquido, fracao: float = 0.01) -> dict:
    x = np.sort(np.asarray(liquido, dtype=float))[::-1]
    k = max(1, int(np.ceil(len(x) * fracao)))
    sobra = float(x.sum() - x[:k].sum())
    return portao(
        "Depende do 1% melhor dos trades?", sobra > 0, False, round(sobra, 2),
        "> 0 sem eles",
        "O lucro tirando o 1% de trades que mais ganharam. Negativo não "
        "reprova, mas diz que o resultado mora em poucas operações.")


def veredito(portoes: list[dict]) -> dict:
    """Crítico reprovado reprova. Crítico ainda não medido impede aprovar.
    Alerta reprovado aprova com ressalva."""
    reprovados = [p for p in portoes if p["critico"] and p["ok"] is False]
    pendentes = [p for p in portoes if p["critico"] and p["ok"] is None]
    ressalvas = [p for p in portoes if not p["critico"] and p["ok"] is False]
    if reprovados:
        estado, cor = "reprovada", "neg"
    elif pendentes:
        estado, cor = "aguardando testes completos", "warn"
    elif ressalvas:
        estado, cor = "aprovada com ressalva", "warn"
    else:
        estado, cor = "aprovada", "pos"
    return {"portoes": portoes, "estado": estado, "cor": cor,
            "n_ok": sum(1 for p in portoes if p["ok"] is True),
            "n_portoes": len(portoes), "reprovados": reprovados,
            "ressalvas": ressalvas, "pendentes": pendentes}
```

- [ ] **Passo 4:** passar, provar discriminação (trocar `ddof=1`/zeros não
interessa: quebre `portao_poucos_dias` somando os piores em vez dos melhores;
quebre `veredito` tratando `None` como aprovado), suíte, commit
`feat(candidata): portões calculados dos dados salvos`.

---

### Tarefa 3: Portão do holdout

**Arquivos:** `core/candidata.py`, `tests/test_candidata.py`.

**Interface:** `portao_holdout(dias, pnl, corte, capital, n=2000, semente=7) -> dict`
— o portão, mais as chaves de leitura `lucro_mes_antes`, `lucro_mes_holdout`,
`esperado_p10` e `pregoes_holdout` no mesmo dicionário.

**Regra (decisão 10 do desenho):** separa a série diária na data do corte.
Com a parte **antes** do corte, simula 2.000 caminhos do mesmo tamanho do
holdout (`robustez.bootstrap(antes, capital, n, semente, horizonte=len(depois))`).
Reprova se o lucro real do holdout ficar abaixo do `final_p10` desses caminhos.

- [ ] **Passo 1: testes que falham**

```python
def _serie(antes, depois, corte="2025-09-15"):
    c = np.datetime64(corte)
    d_antes = np.busday_offset(c, -np.arange(len(antes), 0, -1), roll="backward")
    d_depois = np.busday_offset(c, np.arange(len(depois)), roll="forward")
    return np.concatenate([d_antes, d_depois]), np.concatenate([antes, depois]), c


def test_holdout_igual_ao_historico_passa():
    rng = np.random.default_rng(3)
    dias, pnl, corte = _serie(rng.normal(5, 40, 800), rng.normal(5, 40, 110))
    assert candidata.portao_holdout(dias, pnl, corte, 10_000.0)["ok"] is True


def test_holdout_muito_pior_que_o_historico_reprova():
    rng = np.random.default_rng(3)
    dias, pnl, corte = _serie(rng.normal(5, 40, 800), rng.normal(-15, 40, 110))
    p = candidata.portao_holdout(dias, pnl, corte, 10_000.0)
    assert p["ok"] is False and p["critico"] is True


def test_holdout_melhor_que_o_historico_passa():
    """Melhor que o esperado nunca reprova — o portão só pega o lado ruim."""
    rng = np.random.default_rng(3)
    dias, pnl, corte = _serie(rng.normal(5, 40, 800), rng.normal(30, 40, 110))
    assert candidata.portao_holdout(dias, pnl, corte, 10_000.0)["ok"] is True


def test_curva_sem_holdout_reprova_com_o_motivo():
    rng = np.random.default_rng(3)
    dias, pnl, corte = _serie(rng.normal(5, 40, 800), np.array([]))
    p = candidata.portao_holdout(dias, pnl, corte, 10_000.0)
    assert p["ok"] is False and "holdout" in p["valor"]
```

- [ ] **Passo 2:** ver falhar.

- [ ] **Passo 3: implementação**

```python
def portao_holdout(dias, pnl, corte, capital, n: int = 2000,
                   semente: int = 7) -> dict:
    """O holdout confirma? Compara o que a estratégia fez nos meses do holdout
    com o que a curva ANTES do corte fazia esperar para o mesmo número de
    dias. Só o lado ruim reprova."""
    from . import robustez
    d = np.asarray(dias, dtype="datetime64[D]")
    x = np.asarray(pnl, dtype=float)
    c = np.datetime64(corte, "D")
    antes, depois = x[d < c], x[d >= c]
    nome = "O holdout confirma?"
    dica = ("O holdout são os meses finais que ficaram de fora da mineração. "
            "A plataforma simula 2.000 caminhos do mesmo tamanho usando só o "
            "que a estratégia fez antes deles, e olha onde o resultado real do "
            "holdout caiu. Reprova se ficar entre os 10% piores caminhos. "
            "Resultado melhor que o esperado passa.")
    base = {"lucro_mes_antes": None, "lucro_mes_holdout": None,
            "esperado_p10": None, "pregoes_holdout": int(len(depois))}
    if not len(depois):
        return {**portao(nome, False, True,
                         "sem holdout na curva — salve o walk-forward com o "
                         "holdout marcado", "dentro do esperado", dica), **base}
    boot = robustez.bootstrap(antes, capital, n=n, semente=semente,
                              horizonte=len(depois))
    if not boot:
        return {**portao(nome, None, True, "histórico curto demais",
                         "dentro do esperado", dica), **base}
    real = float(depois.sum())
    p10 = float(boot["final_p10"])
    return {**portao(nome, real >= p10, True, round(real, 2),
                     f"≥ {p10:,.2f} (10% piores)", dica),
            "lucro_mes_antes": float(antes.sum()) / max(len(antes) / 21, 1e-9),
            "lucro_mes_holdout": real / max(len(depois) / 21, 1e-9),
            "esperado_p10": p10, "pregoes_holdout": int(len(depois))}
```

- [ ] **Passo 4:** passar; provar discriminação trocando `real >= p10` por
`real >= boot["final_p50"]` (o teste "igual ao histórico" tem que ficar
instável ou falhar — se não falhar, fortaleça com mais sementes) e
removendo o ramo `not len(depois)`. Suíte, commit
`feat(candidata): portão do holdout`.

---

### Tarefa 4: Teste de muitas tentativas (SPA de Hansen)

**Arquivos:** `core/robustez.py` (extrair o gerador de índices),
criar `core/spa.py`, criar `tests/test_spa.py`.

**Interfaces:**
- `robustez.indices_estacionarios(tamanho, horizonte, n, bloco, rng) -> np.ndarray`
  (forma `(n, horizonte)`) — extraído do corpo de `bootstrap`, que passa a
  chamá-lo. Os testes de `bootstrap` não podem mudar.
- `spa.teste(matriz, n=1000, semente=7, bloco=None) -> dict` com `p`,
  `estatistica`, `melhor` (índice da coluna), `n`.
- `candidata.portao_tentativas(resultado_spa, maximo=0.10) -> dict` (portão 6).

`matriz` tem uma linha por pregão e uma coluna por candidata (cada
combinação fixa minerada, mais a curva do walk-forward), com o resultado
diário. A referência é zero (não operar).

**A conta (Hansen, 2005, versão consistente):**
1. `T` pregões, média `d_k` de cada coluna.
2. Com `n` reamostragens estacionárias das **linhas** (o mesmo sorteio para
   todas as colunas, para manter a correlação entre elas), estime o desvio
   `w_k` de `sqrt(T)·média` de cada coluna.
3. Estatística observada: `max(0, max_k sqrt(T)·d_k / w_k)`.
4. Recentragem: `g_k = d_k` se `sqrt(T)·d_k / w_k ≥ −sqrt(2·log(log(T)))`,
   senão `0`.
5. Em cada reamostragem `b`: `Z_k = sqrt(T)·(média*_k − g_k) / w_k`;
   `T*_b = max(0, max_k Z_k)`.
6. `p = média(T*_b ≥ observada)`.
Colunas com `w_k = 0` saem da conta.

- [ ] **Passo 1: testes que falham**

```python
def test_so_ruido_da_p_alto():
    rng = np.random.default_rng(4)
    m = rng.normal(0, 30, size=(600, 40))
    assert spa.teste(m, n=500)["p"] > 0.2


def test_uma_coluna_com_ganho_forte_da_p_baixo():
    rng = np.random.default_rng(4)
    m = rng.normal(0, 30, size=(600, 40))
    m[:, 7] += 12.0
    r = spa.teste(m, n=500)
    assert r["p"] < 0.05 and r["melhor"] == 7


def test_muitas_tentativas_pesam():
    """O mesmo ganho moderado, sozinho, passa; escondido entre 200 colunas de
    ruído com o mesmo nível, o teste fica mais exigente."""
    rng = np.random.default_rng(5)
    sozinha = rng.normal(3, 30, size=(600, 1))
    muitas = np.hstack([sozinha, rng.normal(0, 30, size=(600, 200))])
    assert spa.teste(muitas, n=500)["p"] > spa.teste(sozinha, n=500)["p"]


def test_mesma_semente_mesmo_p():
    m = np.random.default_rng(6).normal(1, 30, size=(300, 10))
    assert spa.teste(m, n=300, semente=9)["p"] == spa.teste(m, n=300, semente=9)["p"]
```

- [ ] **Passo 2:** ver falhar. **Passo 3:** extrair `indices_estacionarios`
(rodar `tests/test_robustez.py` antes de continuar), escrever `core/spa.py`
seguindo a conta acima, e `portao_tentativas` com nome "Aguenta o desconto
por muitas tentativas?" e uma dica sem sigla: "Foram testadas muitas
combinações; alguma sempre sai bem por sorte. Este teste mede se a melhor
delas continua sendo melhor que não operar depois de descontar isso.
Reprova acima de 10%.". **Passo 4:** passar, provar discriminação (tirar a
recentragem; usar sorteios diferentes por coluna), suíte, commit
`feat(candidata): teste de muitas tentativas`.

---

### Tarefa 5: Entrada aleatória janela a janela

**Arquivos:** `core/aleatorio.py`, `tests/test_aleatorio.py`.

**Interface:**
`teste_janelas(rodar_janela, janelas, alvos, lucro_real, n=1000, semente=7, progresso=None, parar=None) -> dict`
com `p`, `sorteados` (array), `lucro_real`, `sinais_por_janela`,
`trades_obtidos`, `alvos`, `calibracao_ok` (todas as janelas dentro de 5%
do alvo).

- `rodar_janela(janela, n_sinais, semente) -> (n_trades, lucro)` é
  **injetado** — o teste unitário usa uma função falsa; a tarefa 6 liga o
  motor de verdade.
- Calibra **uma vez por janela** (`calibrar`, com semente fixa), depois roda
  `n` repetições; cada repetição soma o lucro de todas as janelas.
- `progresso(feito, total)` a cada repetição; `parar()` verdadeiro
  interrompe e devolve `{}`.
- `p = p_valor(lucro_real, sorteados)`.

Testes com `rodar_janela` falso: (a) sorteio que sempre lucra menos que o
real dá `p` pequeno; (b) sorteio igual ao real dá `p` alto; (c) a calibração
é chamada uma vez por janela, não por repetição (conte as chamadas);
(d) `parar` interrompe; (e) `calibracao_ok` falso quando o alvo é
inatingível.

Escreva também `rodador_do_motor(bars, estrategia_real, perfil, instrumento, trades_reais)`
que devolve a função `rodar_janela` ligada a `run_strategy`: fatia as barras
na janela OOS, monta `EntradaAleatoria` com o histograma de **hora de
execução** das entradas reais daquela janela e a proporção compra/venda
real, e devolve `(len(trades), soma do líquido)`. Um teste de integração
curto com barras sintéticas de 3 pregões garante que ela roda.

Provar discriminação, suíte, commit `feat(candidata): entrada aleatória janela a janela`.

---

### Tarefa 6: Testes completos em segundo plano

**Arquivos:** criar `core/candidata_runner.py` e `tests/test_candidata_runner.py`;
em `core/wfa_runner.py`, extrair a montagem dos argumentos da varredura.

O botão "Rodar testes completos" dispara, numa thread, na ordem:
1. **Varredura da mineração.** Reusa `VARREDURA.cache` quando
   `VARREDURA.estado["run_id"]` é o `run_id` do walk-forward e ela não está
   rodando; senão inicia. Extraia de `ui/callbacks.py` (callback que chama
   `VARREDURA.iniciar`, perto da linha 1278) uma função
   `wfa_runner.argumentos_da_mineracao(run_id) -> dict` e use-a nos dois
   lugares. **Aviso na tela** antes de iniciar uma varredura nova: ela
   substitui a da aba Walk-Forward.
2. **Matriz de resultado diário** de todas as combinações do cache no
   intervalo fora da amostra (mesma soma por dia de saída de
   `candidata.por_pregao`, nos limites de `limites_oos`), mais a coluna da
   curva do walk-forward → `spa.teste` → portão 6.
3. **Reotimizar compensou?** `wfa.faixa_fixas` + `percentil_na_faixa` sobre
   as janelas do walk-forward → alerta (passa com percentil ≥ 50).
4. **Entrada aleatória** → portão 2 (`p ≤ 0,05`). Anote no resultado se a
   calibração ficou fora dos 5% em alguma janela.

Estado publicado (`estado` como dicionário, sob lock): `rodando`, `fase`
(texto simples: "refazendo a varredura", "testando tentativas",
"comparando com parâmetros fixos", "sorteando entradas"), `pct`, `geracao`,
`wfa_id`, `resultado` (os três portões e as leituras), `erro`. Interromper e
descartar resposta de geração antiga, como `Varredura`. Resultado guardado
em memória por `wfa_id` (não no banco nesta etapa).

Testes com dependências injetadas (varredura, rodador e spa falsos): ordem
das fases, interrupção, erro publicado sem derrubar a thread, reuso do
cache quando o `run_id` bate.

Commit `feat(candidata): testes completos em segundo plano`.

---

### Tarefa 7: A faixa de veredito na tela

**Arquivos:** `ui/components/wfa_panel.py` (o `selo` ganha parâmetro
`titulo`, padrão atual), `ui/components/candidata_panel.py`,
`ui/callbacks_candidata.py`, `ui/assets/style.css`,
`tests/test_callbacks_candidata.py`, `tests/test_callbacks_sem_ciclo.py`.

- No topo do painel (`cand-portoes`), o selo com título **"a estratégia
  está pronta para a incubação?"**, estado e a lista de portões.
- Portões 1, 3, 4, 5, 7, 8 e os alertas de vizinho, 1% dos trades e faixa
  testada saem na hora, ao escolher o walk-forward. Portões 2 e 6 e o alerta
  de reotimização aparecem como **"—  aguardando"** até os testes completos
  rodarem; o selo diz "aguardando testes completos".
- `portao` com `ok is None`: marca "…", classe `pendente` (cinza).
- Botão **"Rodar testes completos"** e barra de progresso com o texto da
  fase, no padrão da aba Walk-Forward (store que muda uma vez por fase, não
  o relógio). Botão travado enquanto roda.
- Na tabela "Resultado fora da amostra", uma linha nova **"holdout"** com
  "R$ X/mês no holdout · R$ Y/mês antes do corte", sem cor.
- Na seção "Quanto a estratégia aguenta", acrescente à explicação do (?) que
  os números ruins de cada linha não acontecem todos ao mesmo tempo.
- Montagem dos portões rápidos numa função pura
  `candidata.portoes_rapidos(detalhes, trades, leitura, trials, espaco, corte, tick_value, capital) -> list[dict]`,
  testada sem Dash.
- `tick_value`: do YAML do instrumento, pelo mesmo carregador que o backtest usa.

Conferir no navegador: #8 escolhido, selo com os portões rápidos, clique em
"Rodar testes completos", barra andando, veredito final. Teste de ciclo
inteiro. Commit `feat(candidata): veredito na tela`.

---

### Tarefa 8: Documentação

- `docs/CALCULOS-CANDIDATA.md` (novo), no formato do `CALCULOS-WFA.md`: cada
  portão com a pergunta, a conta, a regra e o número real do walk-forward #8.
  **Linguagem simples**; fórmula só onde ajuda.
- `CHANGELOG.md`: a etapa 2.
- `docs/METODOLOGIA.md`: passo 10 com o estado novo.
- `docs/PLANO-CANDIDATA.md`: marcar a etapa 2 como feita.

Commit `docs(candidata): etapa 2`.
