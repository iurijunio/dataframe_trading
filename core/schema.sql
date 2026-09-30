-- Camada de dados do Dataframe.
--
-- A base e um ARQUIVO PERMANENTE: o MT5 so serve ~5 anos de M1 do mini indice,
-- entao cada exportacao e somada as anteriores e nada aqui e apagado.
-- Por isso a ingestao e um merge com resolucao deterministica de conflito,
-- e nao uma carga.

-- ---------------------------------------------------------------- camada 1
CREATE TABLE IF NOT EXISTS instruments (
    symbol           VARCHAR PRIMARY KEY,
    description      VARCHAR,
    exchange         VARCHAR,
    currency         VARCHAR,
    timezone         VARCHAR,
    price_decimals   INTEGER,
    tick_size        INTEGER,   -- em pontos
    point_value      DOUBLE,    -- R$ por ponto, por contrato
    tick_value       DOUBLE,    -- tick_size * point_value
    allows_overnight BOOLEAN,
    rollover_policy  VARCHAR
);

-- ------------------------------------------------------------- historico
-- src_ingest_id aponta para a exportacao que forneceu esta versao da barra.
-- E o que torna o merge independente da ordem de importacao: numa colisao,
-- vence a exportacao mais recente, nao a ultima a ser importada.
CREATE TABLE IF NOT EXISTS bars_m1 (
    symbol        VARCHAR   NOT NULL,
    ts            TIMESTAMP NOT NULL,
    open          BIGINT    NOT NULL,
    high          BIGINT    NOT NULL,
    low           BIGINT    NOT NULL,
    close         BIGINT    NOT NULL,
    tick_volume   BIGINT,
    volume        BIGINT,
    spread        INTEGER,
    src_ingest_id BIGINT    NOT NULL,
    PRIMARY KEY (symbol, ts)
);

-- Toda carga fica registrada. source_max_ts e o timestamp da barra mais
-- recente do arquivo e funciona como "quao nova e esta exportacao".
CREATE TABLE IF NOT EXISTS ingest_log (
    ingest_id       BIGINT PRIMARY KEY,
    symbol          VARCHAR,
    source_file     VARCHAR,
    source_sha256   VARCHAR,
    source_min_ts   TIMESTAMP,
    source_max_ts   TIMESTAMP,
    rows_in_file    BIGINT,
    rows_inserted   BIGINT,   -- barras que nao existiam
    rows_updated    BIGINT,   -- divergencias em que esta exportacao venceu
    rows_rejected   BIGINT,   -- divergencias em que a base ja tinha versao mais nova
    rows_identical  BIGINT,
    conflict_sample VARCHAR,  -- JSON com ate 5 exemplos de divergencia
    ingested_at     TIMESTAMP
);

-- --------------------------------------------------------------- derivadas
-- Reconstruidas a partir de bars_m1. Nunca sao fonte da verdade.
CREATE TABLE IF NOT EXISTS trading_days (
    symbol     VARCHAR NOT NULL,
    date       DATE    NOT NULL,
    first_ts   TIMESTAMP,
    last_ts    TIMESTAMP,
    bar_count  INTEGER,
    is_partial BOOLEAN,
    PRIMARY KEY (symbol, date)
);

-- Datas de virada de contrato. Dorme enquanto so houver day trade no WIN;
-- vira obrigatoria no primeiro instrumento com allows_overnight = true.
CREATE TABLE IF NOT EXISTS rollovers (
    symbol      VARCHAR NOT NULL,
    date        DATE    NOT NULL,  -- primeiro pregao do novo contrato
    prev_date   DATE,
    prev_close  BIGINT,
    next_open   BIGINT,
    gap_points  BIGINT,
    detected_by VARCHAR,           -- 'calendar' | 'calendar+gap'
    PRIMARY KEY (symbol, date)
);

-- ---------------------------------------------------------------- camada 4
-- Perfil de execucao: janela, limites diarios, custos e dimensionamento.
-- Identico para toda estrategia, editavel na tela, salvo aqui.
-- Cada run guarda um RETRATO deste JSON, nunca uma referencia: mudar o
-- perfil depois nao pode reescrever o passado.
CREATE TABLE IF NOT EXISTS execution_profiles (
    profile_id BIGINT PRIMARY KEY,
    name       VARCHAR UNIQUE NOT NULL,
    config     JSON NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- --------------------------------------------------------------- mineracao
-- Cada run guarda o RETRATO do perfil de execucao que a gerou, nao uma
-- referencia. Custo editavel na tela + referencia = duas minerações de dias
-- diferentes viram comparacao entre coisas incomparaveis, sem aviso.
-- So chega aqui o que voce mandou salvar. Minerar e exploratorio: dezenas de
-- varreduras ate achar cluster, e a maioria e lixo que nao merece disco.
CREATE TABLE IF NOT EXISTS mining_runs (
    run_id         BIGINT PRIMARY KEY,
    symbol         VARCHAR,
    strategy       VARCHAR,
    created_at     TIMESTAMP,
    profile        JSON,     -- retrato completo da camada 4
    space          JSON,     -- espaco de busca varrido
    folds          JSON,     -- janelas de teste
    holdout_de     VARCHAR,  -- a partir daqui, nada foi olhado
    n_combinacoes  BIGINT,
    status         VARCHAR,
    nome           VARCHAR,  -- rotulo que voce deu na hora de salvar
    wf_config      JSON      -- treino/teste/passo/holdout da varredura
);

-- O holdout fica gravado mas NAO e exibido durante a varredura: mostrar o
-- holdout de mil combinacoes e escolher a melhor e o mesmo que nao ter
-- holdout. Ele e para uma olhada so, na hora de decidir.
CREATE TABLE IF NOT EXISTS mining_trials (
    run_id          BIGINT,
    trial_id        BIGINT,
    params          JSON,
    trades          BIGINT,   -- periodo de otimizacao
    lucro           DOUBLE,
    profit_factor   DOUBLE,
    max_dd          DOUBLE,
    folds_com_trades BIGINT,  -- consistencia entre periodos
    folds_positivos  BIGINT,
    mediana_fold    DOUBLE,
    holdout_trades  BIGINT,   -- lacrado ate a revelacao deliberada
    holdout_lucro   DOUBLE,
    score           DOUBLE,
    passa_filtro    BOOLEAN,
    erro            VARCHAR,
    score_robusto   DOUBLE,   -- mediana dos vizinhos na grade
    PRIMARY KEY (run_id, trial_id)
);

-- Bancos criados antes destas colunas existirem: ADD COLUMN e no-op quando a
-- coluna ja veio do CREATE acima.
ALTER TABLE mining_runs   ADD COLUMN IF NOT EXISTS nome VARCHAR;
-- treino/teste/passo/holdout usados na varredura. Sem isto, carregar uma
-- mineracao e clicar numa linha recalculava o corte do holdout com os valores
-- que estivessem na tela - outro corte, outro lucro para a mesma combinacao.
ALTER TABLE mining_runs   ADD COLUMN IF NOT EXISTS wf_config JSON;
-- os critérios de aceite que estavam na tela ao salvar. O walk-forward os
-- aplica dentro de cada janela IS; sem eles, cada janela escolhia entre TODAS
-- as combinações, inclusive as que perdiam dinheiro no próprio IS.
ALTER TABLE mining_runs   ADD COLUMN IF NOT EXISTS criterios JSON;
ALTER TABLE mining_trials ADD COLUMN IF NOT EXISTS score_robusto DOUBLE;

-- ------------------------------------------------------------ walk-forward
-- O resultado de um WFA e barato de recalcular (o custo esta na varredura,
-- nao nas janelas), entao o que se guarda aqui e o REGISTRO da decisao: qual
-- mineracao, com que janela e que inteligencia, e o que deu. E o historico
-- de "eu ja testei isto assim" que evita refazer o mesmo caminho.
CREATE TABLE IF NOT EXISTS wfa_runs (
    wfa_id        BIGINT PRIMARY KEY,
    run_id        BIGINT,    -- a mineracao que forneceu o espaco
    symbol        VARCHAR,
    strategy      VARCHAR,
    created_at    TIMESTAMP,
    nome          VARCHAR,
    is_meses      INTEGER,
    oos_meses     INTEGER,
    inteligencia  VARCHAR,
    holdout       BOOLEAN,   -- a varredura foi estendida ao holdout?
    janelas       INTEGER,
    oos_lucro     DOUBLE,
    oos_trades    BIGINT,
    wfe_global    DOUBLE,
    consistencia  DOUBLE,
    dd_oos        DOUBLE,
    veredito      VARCHAR,
    passos        JSON,      -- uma linha por janela, com o parametro escolhido
    deploy        JSON       -- a combinacao que se colocaria para operar hoje
);

-- A Candidata (passo 10 da metodologia) lê só wfa_runs + wfa_trades: o
-- capital e o perfil vinham da mineracao, e mineracao apagada derrubava o
-- dimensionamento inteiro. Retrato, nao referencia.
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS profile JSON;
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS capital DOUBLE;
-- os sharpes das 96 celulas da matriz: entrada do Sharpe Deflacionado
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS sharpes_matriz JSON;

-- A camada 4 (stop, alvo, protecoes) foi travada na primeira janela, ou
-- reotimizada junto com o resto? Muda o que o plano de operacao promete: com
-- ela travada o disjuntor vale ate a proxima troca de parametro; solta, ele
-- e regravado a cada reotimizacao.
ALTER TABLE wfa_runs ADD COLUMN IF NOT EXISTS camada4_travada BOOLEAN;

-- Os TRADES da curva fora da amostra, um por linha.
--
-- O agregado por janela nao serve para portfolio: correlacao de verdade pede
-- a serie, e exposicao simultanea pede saber QUANDO cada posicao esteve
-- aberta. Com entrada e saida por trade da para reagregar em qualquer
-- frequencia, medir sobreposicao de exposicao e condicionar a correlacao aos
-- piores dias - nada disso se reconstroi a partir de um total mensal.
--
-- E sao os trades OOS de proposito. Montar portfolio com backtests otimizados
-- e correlacionar dois sobreajustes; a curva concatenada do walk-forward e a
-- unica aqui que o otimizador nunca enxergou.
CREATE TABLE IF NOT EXISTS wfa_trades (
    wfa_id     BIGINT,
    n          BIGINT,     -- ordem na curva concatenada
    step       INTEGER,    -- a janela que escolheu o parametro deste trade
    entry_ts   TIMESTAMP,
    exit_ts    TIMESTAMP,
    side       INTEGER,    -- +1 compra, -1 venda
    entry_px   BIGINT,
    exit_px    BIGINT,
    points     BIGINT,
    contratos  BIGINT,
    bruto      DOUBLE,
    custo      DOUBLE,
    liquido    DOUBLE,
    reason     INTEGER,    -- stop, alvo, sinal, fechamento, tempo, fim
    mae        BIGINT,
    mfe        BIGINT,
    bars_held  BIGINT,
    PRIMARY KEY (wfa_id, n)
);

-- ------------------------------------------------------ plano de operacao
-- O fim do passo 10: o que a incubacao vai ler e o que a operacao vai
-- obedecer. Tudo aqui e RETRATO, nao referencia - mineracao apagada nao pode
-- mudar o tamanho de posicao de quem ja esta operando.
--
-- Sem UNIQUE por wfa_id de proposito: dois planos do mesmo walk-forward com
-- risco diferente sao duas DECISOES, e ambas sao historico. Plano nao se
-- edita: aposenta-se (estado) e grava-se outro.
CREATE TABLE IF NOT EXISTS planos_operacao (
    plano_id        BIGINT PRIMARY KEY,
    wfa_id          BIGINT,
    run_id          BIGINT,
    symbol          VARCHAR,
    strategy        VARCHAR,
    nome            VARCHAR,
    created_at      TIMESTAMP,
    params          JSON,     -- retrato dos parametros que vao operar
    profile         JSON,     -- retrato da camada 4
    capital         DOUBLE,
    contratos       INTEGER,
    risco_pedido_pct  DOUBLE, -- por PREGAO, nao por operacao
    risco_efetivo_pct DOUBLE, -- o do inteiro escolhido
    perda_referencia  DOUBLE,
    de_onde         VARCHAR,  -- qual leitura dimensionou
    margem          DOUBLE,
    uso_margem_pct  DOUBLE,
    camada4_travada BOOLEAN,
    disjuntor       JSON,     -- os dois niveis e as taxas de alarme falso
    expectativa     JSON,     -- faixa p10-p90 em 3, 6 e 12 meses
    reotimizacao    JSON,     -- a receita inteira, nao so a data
    definicoes      JSON,     -- novo topo, reentrada, posicao aberta...
    regua           JSON,     -- limiares congelados + resultado do holdout
    estado          VARCHAR   -- 'ativo' | 'aposentado'
);

-- Reprodutibilidade e vencimento. Os retratos acima protegem contra a
-- mineracao sumir; estas colunas protegem contra o MOTOR mudar. Uma alteracao
-- de slippage, de regra de preenchimento ou um reingest com correcao de
-- rollover muda os numeros que este plano gravou, e sem isto nao ha como
-- saber qual motor e qual base produziram a decisao.
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS motor_versao VARCHAR;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS base_ate TIMESTAMP;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS base_barras BIGINT;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS capital_livre DOUBLE;
-- coluna, nao campo dentro do JSON: a incubacao vai perguntar "quais planos
-- vencem esta semana", e isso nao se consulta dentro de um JSON
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS reotimizar_em DATE;

CREATE SEQUENCE IF NOT EXISTS seq_plano_id START 1;

-- ---------------------------------------------------- identidade da estrategia
-- Reotimizar (minerar de novo, rodar o WFA de novo, gravar outro plano) nao
-- deixa rastro de que aquilo e a MESMA estrategia de antes, so atualizada.
-- Esta tabela agrupa os ciclos que pertencem a uma mesma variante; WFA e
-- plano herdam por cascata (run_id -> variante_id), sem coluna propria.
CREATE TABLE IF NOT EXISTS estrategia_variantes (
    variante_id  BIGINT PRIMARY KEY,
    estrategia   VARCHAR NOT NULL,
    nome         VARCHAR NOT NULL,
    descricao    VARCHAR,
    criado_em    TIMESTAMP NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS seq_variante_id START 1;

-- ligacao opcional: minerar sem escolher variante continua funcionando
ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS variante_id BIGINT;

-- portfolio: agrupa variantes, nunca plano/wfa/mineracao diretamente -
-- "o que esta ativo hoje" e sempre resolvido na hora via
-- variantes.plano_ativo, para reotimizar uma variante atualizar o
-- portfolio sozinho, sem editar nada aqui.
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id  BIGINT PRIMARY KEY,
    nome          VARCHAR NOT NULL,
    criado_em     TIMESTAMP NOT NULL
);
-- capital da CONTA que roda o portfolio inteiro - independente do
-- capital de cada plano individual (esse so dimensiona a POSICAO daquela
-- variante sozinha). Sem isto, a curva combinada nao tem de onde partir:
-- somar o capital de cada plano assumia contas separadas por variante,
-- quando na pratica e a MESMA conta rodando as duas juntas (achado real
-- do usuario, 28/09/2026). NULL ate o usuario digitar.
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS capital DOUBLE;
CREATE SEQUENCE IF NOT EXISTS seq_portfolio_id START 1;

CREATE TABLE IF NOT EXISTS portfolio_variantes (
    portfolio_id  BIGINT NOT NULL,
    variante_id   BIGINT NOT NULL,
    adicionado_em TIMESTAMP NOT NULL,
    PRIMARY KEY (portfolio_id, variante_id)
);

CREATE SEQUENCE IF NOT EXISTS seq_wfa_id START 1;

CREATE SEQUENCE IF NOT EXISTS seq_ingest_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_profile_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_run_id START 1;

-- ----------------------------------------------------------------- ao vivo
-- Spec: docs/superpowers/specs/2026-09-30-ao-vivo-estrategias-design.md.
-- O que está ligado, em que fase e para qual conta. Diferente do resto do
-- banco, isto NÃO se reconstrói a partir dos CSVs: é decisão do usuário.

-- conta nunca se apaga, só se arquiva: as ordens da parte 4 vão apontar
-- para ela. Nome único entre as não arquivadas é checado em código (o
-- DuckDB não tem UNIQUE parcial).
CREATE SEQUENCE IF NOT EXISTS seq_conta_id START 1;
CREATE TABLE IF NOT EXISTS contas (
    conta_id         BIGINT PRIMARY KEY,
    nome             VARCHAR NOT NULL,
    tipo             VARCHAR NOT NULL,     -- 'demo' | 'real'
    limite_perda_dia DOUBLE,               -- R$, opcional (mesa proprietária)
    criado_em        TIMESTAMP NOT NULL,
    arquivada_em     TIMESTAMP
);

ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS ligado BOOLEAN DEFAULT false;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_demo_id BIGINT;
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS conta_real_id BIGINT;

-- substitui portfolio_variantes: a chave composta de lá não deixa uma
-- variante voltar ao portfólio sem apagar o histórico, e a parte 4 precisa
-- de um número por ligação para etiquetar a ordem no MT5
CREATE SEQUENCE IF NOT EXISTS seq_ligacao_id START 1;
CREATE TABLE IF NOT EXISTS portfolio_membros (
    ligacao_id         BIGINT PRIMARY KEY,
    portfolio_id       BIGINT NOT NULL,
    variante_id        BIGINT NOT NULL,
    adicionado_em      TIMESTAMP NOT NULL,
    removido_em        TIMESTAMP,          -- remoção só marca, nunca apaga
    fase               VARCHAR NOT NULL,   -- 'papel'|'demo'|'real_minimo'|'real'
    fase_desde         TIMESTAMP NOT NULL,
    ligada             BOOLEAN NOT NULL,
    desligada_por      VARCHAR,            -- 'usuario' | 'disjuntor'
    desligada_em       TIMESTAMP,
    desligada_plano_id BIGINT              -- plano em vigor ao desligar (informativo)
);

-- diário: SÓ INSERÇÃO. Nenhum código faz UPDATE/DELETE aqui (há teste que
-- varre o fonte). É a única informação que não se recria depois.
CREATE SEQUENCE IF NOT EXISTS seq_evento_id START 1;
CREATE TABLE IF NOT EXISTS ao_vivo_eventos (
    evento_id     BIGINT PRIMARY KEY,
    quando        TIMESTAMP NOT NULL,
    tipo          VARCHAR NOT NULL,
    origem        VARCHAR NOT NULL,     -- 'usuario' | 'disjuntor' | 'sistema'
    portfolio_id  BIGINT,
    ligacao_id    BIGINT,
    variante_id   BIGINT,
    conta_id      BIGINT,
    plano_id      BIGINT,
    de            VARCHAR,
    para          VARCHAR,
    motivo        VARCHAR
);

-- o plano sabe de que variante é SEM depender da mineração (retrato): a
-- mineração pode ser apagada, o histórico da variante não
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS variante_id BIGINT;
-- vigência: o plano novo só vale no próximo pregão, e o antigo vale até lá
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS vale_a_partir DATE;
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS aposentado_em DATE;
-- impressão digital do código que gerou os números (ver core/codigo.py)
ALTER TABLE planos_operacao ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;
ALTER TABLE wfa_runs        ADD COLUMN IF NOT EXISTS codigo_hash VARCHAR;

-- migração (roda a cada subida, idempotente): cada portfolio_variantes
-- vira membro no papel, ligado — SÓ se não existe membro nenhum para o
-- par, REMOVIDO OU NÃO. Contar só os ativos ressuscitaria a variante
-- removida a cada reinício.
INSERT INTO portfolio_membros (ligacao_id, portfolio_id, variante_id,
    adicionado_em, fase, fase_desde, ligada)
SELECT nextval('seq_ligacao_id'), pv.portfolio_id, pv.variante_id,
       pv.adicionado_em, 'papel', pv.adicionado_em, true
FROM portfolio_variantes pv
WHERE NOT EXISTS (SELECT 1 FROM portfolio_membros m
                  WHERE m.portfolio_id = pv.portfolio_id
                    AND m.variante_id = pv.variante_id);

UPDATE planos_operacao SET variante_id = (
    SELECT m.variante_id FROM mining_runs m
    WHERE m.run_id = planos_operacao.run_id)
WHERE variante_id IS NULL;
