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

CREATE SEQUENCE IF NOT EXISTS seq_wfa_id START 1;

CREATE SEQUENCE IF NOT EXISTS seq_ingest_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_profile_id START 1;
CREATE SEQUENCE IF NOT EXISTS seq_run_id START 1;
