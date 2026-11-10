# Dataframe — instruções do projeto

> Núcleo limitado por teste; detalhes nas regras por área.

Plataforma Python (Dash + DuckDB + Numba) para pesquisar e operar day trade.
Ramo principal `master`; remoto `origin` no GitHub.

**⚠ Há estratégias operando na conta real.** Nunca envie ordem nem zere posição:
o usuário faz isso na tela ou no MT5.

## O usuário

- Trader, não programador: português direto, termo novo com exemplo dos dados dele.
- Prefere **ver funcionando na tela**: resultado se mostra com screenshot.
- Ele dá o aval final. Não commite, não faça merge nem push sem ele pedir.

## Rodar

Python 3.13.7, venv + pip:

```
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Não recrie o ambiente. Dependências de tela comentadas em `requirements.txt`:
instalação incompleta. Build/lint/typecheck não configurados; não invente comandos.

```
.venv/Scripts/python.exe ui/app.py          # http://127.0.0.1:8050
.venv/Scripts/python.exe -m pytest -q tests/<arquivo>.py
.venv/Scripts/python.exe -m pytest -q       # suíte inteira
```

- Não abra `iniciar.bat`, captura ou ordens reais: iniciam serviços que podem
  operar. Quem os abre é o usuário. A interface também aplica o esquema do banco.
- Não altere dependências, secrets, deploy, CI ou arquivos gerados sem autorização.
- Nunca use `git clean -x`: apaga o banco e o diário ignorados pelo Git.
- Para ver o app, `preview_start` com o nome `dataframe`; **só com o app real
  fechado**, porque a cópia abre o banco real.
- **Git**: mensagem de commit com mais de uma linha vai num arquivo do
  scratchpad, com `git commit -F <arquivo>`; nunca heredoc (quebra com acentos).
- Adicione arquivos ao commit **pelo caminho**, nunca `git add -A` / `git add .`.
  Alteração que você não fez é do usuário: não stageie.
- **Worktrees:** `data/` e `.venv/` são junções para os originais. Remova com
  `cmd /c rmdir`, nunca `rm -rf`, ou apaga o banco real.

## Contexto barato

Busque com `rg`, leia trechos; nunca o `CHANGELOG.md` inteiro. Antes de editar,
identifique os testes mínimos e leia `AGENTS.md` locais; expanda só por dependência.

## Tamanho da tarefa

Classifique antes de começar e use o **menor** fluxo que cabe:

- **Micro** (texto, CSS, renomear, pergunta de "onde fica"): faça direto, sem
  plano nem subagente.
- **Simples** (poucos arquivos, sem conta/estado/banco): localizar → editar →
  teste do arquivo tocado.
- **Impacto**: o fluxo abaixo, inteiro.

## Como trabalhar

**Mudança de impacto** (conta, lógica, dado, banco, callback com estado):

1. Teste falhando → implementação mínima → teste passando.
2. **Mutação**: quebre a implementação de propósito, confirme que o teste
   pega, desfaça (agente `mutacao`). Teste que passa com código errado não prova nada.
3. Revisão em segundo plano (agente `revisor`) → aplicar o que procede.
4. Suíte inteira verde → conferir na tela contra o banco real, com o app e
   serviços reais fechados. Commit apenas se o usuário pedir.

**Mudança simples de layout/CSS/texto**: sem testes, sem mutação, sem
revisão. Faça, mostre na tela (screenshot) e **o usuário aprova**.

**Depois de mudar código**, rode `.venv/Scripts/python.exe scripts/conferir.py`:
ele diz o que conferir e o que reabrir. Avise o usuário em destaque; o app
aberto não carrega código novo.

**Concluída:** escopo implementado e verificações exigidas passando; explique
comandos, falhas, limites e reaberturas. Lint/typecheck só quando configurados.
Relate validação pendente. O lembrete de suíte do script não elimina a exceção
de layout; documentação exige validar instruções, não a suíte de produção.

## Regras do código

- Código, nomes, comentários e textos de tela em **português**.
- Comentário explica **por quê**; referência: `core/wfa.py`.
- **Nada em `core/` importa Dash.** `core/` são contas; `ui/` liga a tela.
- **Nenhum teste toca `data/database.duckdb`.** Todo teste já roda isolado do
  banco real por `tests/conftest.py` (autouse); mesmo assim use a fixture
  `banco`: `monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.duckdb")` (e
  `PARQUET_DIR` quando ler barras). Veja `tests/test_portfolio.py`.
- Toda métrica nova na tela tem um (?) com faixa boa e ruim (`ui/components/cartao.py`).
- Sem scipy, de propósito (`core/robustez.py` usa `math.erfc`).
- Não desligar o logo da TradingView no gráfico — exigência da licença.
- Base de referência: `WIN$N`, 16/03/2021 em diante, capital padrão R$ 10.000.
- Não fixe valores ou itens específicos onde a regra é geral: leia do código.

## Glossário (use estes nomes com o usuário)

- **Estratégia** — o código em `strategies/*.py`.
- **Variante** — configuração salva e nomeada pelo usuário. Clusters distintos
  são variantes distintas. Atravessa reotimizações: só troca de plano.
- **Plano** — parâmetros, contratos e disjuntor gravados pela Candidata;
  **um plano ativo por variante**.
- **Fase** — por portfólio: papel → demo → real. Nunca "degrau" ou "real mínimo";
  `real_minimo` do banco migra para `real`.
- **Serviço de captura** — processo de candles ao vivo e automação operacional,
  aberto pelo usuário via `iniciar.bat`. Nunca "robô".

## Armadilhas que valem para tudo

- **DuckDB: vários leitores OU um escritor.** Workers: `db.read_bars_parquet`;
  escrita: `db.connect_write()`.
- **`COPY … TO ?` com parâmetro não grava nada, em silêncio** — caminho literal via `_sql_str`.
- **Ciclo entre callbacks congela a tela.** Rode `tests/test_callbacks_sem_ciclo.py`
  sempre que mexer em Inputs/Outputs.
- Nunca mandar as ~700 mil barras ao navegador — `ui/data.py` agrega pelo `MAX_CANDLES`.
- Look-ahead é travado no kernel: sinal da barra `i` executa na abertura de `i+1`.
- **O `.duckdb` deixou de ser só cache:** `contas`, `portfolio_membros`,
  `ao_vivo_eventos`, `planos`, `papel_operacoes`, `papel_pregoes`,
  `ordens_eventos` e `papel_backtest` não se recriam — backup antes de qualquer
  migração; nunca apagar o banco. Também nunca se apaga o diário de escrita
  adiantada `data/ao_vivo/ordens/*.jsonl`: é dele (não do banco) que a captura
  relê "já enviei a entrada X" e "conta travada hoje".

## Regras por área

Leia as regras aplicáveis antes de editar, inclusive em subagentes. Não presuma
carregamento automático: siga o encaminhamento específico do cliente utilizado.
Referências existentes do projeto:

| A tarefa toca… | Regra |
|---|---|
| captura, MT5, candles, papel, reconferência | `.claude/rules/captura-papel.md` |
| ordens, conta real, ponte, promoção de fase | `.claude/rules/ordens.md` |
| motor, estratégias, `codigo_hash` | `.claude/rules/motor-estrategias.md` |
| mineração, faixas, campos do menu | `.claude/rules/mineracao.md` |
| Busca automática | `.claude/rules/busca.md` |
| MES/MNQ, escala, unidades | `.claude/rules/cme.md` |
| Portfólio | `.claude/rules/portfolio.md` |
| qualquer tela | `.claude/rules/tela.md` |

Para retomar entrega, ver pendências ou saber qual documento confiar:
`docs/agentes/estado.md`. Mapa dos arquivos: `docs/agentes/arquitetura.md`.
Mapa: `core/` contas/dados; `strategies/` sinais; `configs/` parâmetros;
`ui/` tela; `tests/` isolamento; `scripts/` conferências. Fluxo: dados → mineração
→ WFA → Candidata → plano da variante → portfólio → papel/demo/real.

## Agentes do projeto

Use agentes apenas quando pouparem trabalho real, conforme o tamanho da tarefa.
Sem agente disponível, relate a execução própria; não declare revisão independente.
