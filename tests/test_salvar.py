"""Salvar é decisão sua: nada de mineração vai para o banco sozinho.

Estes testes guardam duas promessas:
  1. varrer não grava — só o botão grava;
  2. o INSERT tem exatamente as colunas de mining_trials, na ordem certa.

A segunda parece boba até a tabela ganhar uma coluna e o insert calar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import optimizer as opt  # noqa: E402
from core import walkforward as wf  # noqa: E402


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "t.duckdb"
    monkeypatch.setattr(db, "DB_PATH", caminho)
    with db.connect() as con:
        db.init_schema(con)
    return caminho


def resultado(trial_id: int, lucro: float, robusto: float | None = 1.5) -> dict:
    r = {
        "trial_id": trial_id,
        "params": {"media_rapida": 5 + trial_id, "media_lenta": 40},
        "geral": {"trades": 120, "lucro": lucro, "profit_factor": 1.3,
                  "max_dd": 500.0, "fator_recuperacao": 2.0, "expectativa": 1.0},
        "folds": {"n": 12, "com_trades": 11, "positivos": 8,
                  "mediana_fr": 1.2, "mediana_lucro": 90.0},
        "consistencia": 8 / 11,
        "holdout": {"trades": 30, "lucro": 250.0, "profit_factor": 1.1,
                    "max_dd": 100.0, "fator_recuperacao": 2.5, "expectativa": 8.3},
        "passa_filtro": True,
        "score": 1.2,
        "erro": None,
    }
    if robusto is not None:
        r["score_robusto"] = robusto
    return r


def mineracao_pronta(nome_estrategia="setup_cruzamento") -> opt.Mineracao:
    m = opt.Mineracao()
    m._resultados = [resultado(i, 100.0 * i) for i in range(5)]
    m._contexto = {
        "symbol": "TEST$N", "estrategia": nome_estrategia,
        "perfil": {"capital_inicial": 10_000.0, "contratos": 1},
        "espaco": {"media_rapida": [5, 6, 7, 8, 9], "media_lenta": [40]},
        "janelas": wf.montar_janelas("2021-03-16", "2026-03-13"),
        "total": 5, "interrompida": False,
    }
    return m


def contar(banco) -> tuple[int, int]:
    with db.connect(read_only=True) as con:
        runs, = con.execute("SELECT count(*) FROM mining_runs").fetchone()
        trials, = con.execute("SELECT count(*) FROM mining_trials").fetchone()
    return runs, trials


# ---------------------------------------------------------------- promessas
def test_varredura_nao_grava_sozinha(banco):
    m = mineracao_pronta()
    assert contar(banco) == (0, 0)      # resultado em memória, banco intacto
    assert m.pode_salvar


def test_salvar_grava_tudo_com_nome(banco):
    m = mineracao_pronta()
    m._persistir("cruzamento tentativa 1")

    runs, trials = contar(banco)
    assert (runs, trials) == (1, 5)
    assert m.estado["salva"] is True
    assert "tentativa 1" in m.estado["aviso_salvar"]

    with db.connect(read_only=True) as con:
        nome, status, n = con.execute(
            "SELECT nome, status, n_combinacoes FROM mining_runs"
        ).fetchone()
    assert nome == "cruzamento tentativa 1"
    assert status == "concluida"
    assert n == 5


def test_colunas_gravadas_na_ordem_certa(banco):
    """O INSERT é posicional: uma coluna fora de ordem grava lucro em max_dd
    sem erro nenhum."""
    m = mineracao_pronta()
    m._persistir(None)

    with db.connect(read_only=True) as con:
        linha = con.execute(
            "SELECT trades, lucro, profit_factor, max_dd, folds_com_trades, "
            "folds_positivos, mediana_fold, holdout_trades, holdout_lucro, "
            "score, passa_filtro, score_robusto "
            "FROM mining_trials WHERE trial_id = 3"
        ).fetchone()

    assert linha == (120, 300.0, 1.3, 500.0, 11, 8, 90.0, 30, 250.0,
                     1.2, True, 1.5)


def test_interrompida_e_registrada_como_tal(banco):
    m = mineracao_pronta()
    m._contexto["interrompida"] = True
    m._persistir(None)
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT status FROM mining_runs").fetchone()[0] == "interrompida"


def test_nao_salva_duas_vezes(banco):
    m = mineracao_pronta()
    m._persistir(None)
    assert not m.pode_salvar
    assert m.salvar("de novo") is False
    assert contar(banco) == (1, 5)


def test_combinacao_sem_score_robusto_nao_quebra(banco):
    """Combinação sem trade nenhum não recebe score de vizinhança."""
    m = mineracao_pronta()
    m._resultados.append(resultado(99, 0.0, robusto=None))
    m._resultados[-1]["score"] = float("-inf")
    m._persistir(None)

    with db.connect(read_only=True) as con:
        score, robusto = con.execute(
            "SELECT score, score_robusto FROM mining_trials WHERE trial_id = 99"
        ).fetchone()
    assert score is None and robusto is None   # -inf vira NULL, não erro


def test_nova_varredura_descarta_a_anterior_nao_salva(banco):
    m = mineracao_pronta()
    assert m.pode_salvar
    # iniciar() limpa o que estava em memória antes de arrancar a thread
    m.estado.update(rodando=True)
    assert m.iniciar() is False        # não começa outra por cima
    m.estado.update(rodando=False)


def test_sanear_fecha_runs_orfas(banco):
    m = mineracao_pronta()
    m._persistir(None)
    with db.connect() as con:
        con.execute("UPDATE mining_runs SET status = 'rodando'")

    assert opt.sanear_runs_orfas() == 1
    with db.connect(read_only=True) as con:
        # tem trials gravados, então foi interrompida - não abandonada
        assert con.execute("SELECT status FROM mining_runs").fetchone()[0] == "interrompida"


# ------------------------------------------------ troca de estrategia
def test_esquecer_descarta_a_varredura(banco):
    m = mineracao_pronta()
    assert m.pode_salvar
    m.esquecer()
    assert m.n_resultados == 0
    assert m.estado["trials"] == []
    assert not m.pode_salvar
    assert contar(banco) == (0, 0)


def test_varredura_obsoleta_nao_repovoa_a_tela(banco):
    """Trocar de estratégia no meio de uma mineração.

    A thread antiga continua viva por alguns instantes. Sem o contador de
    geração ela terminava e reescrevia `trials` DEPOIS do reset — a tela
    voltava a mostrar combinações de uma estratégia que não está mais
    selecionada, com parâmetros que nem existem nos campos.
    """
    m = opt.Mineracao()
    geracao_da_thread = m._geracao

    m.esquecer()                     # simula a troca de estratégia
    assert m._geracao != geracao_da_thread

    # a thread antiga só escreveria se ainda fosse da geração dela
    viva = m._geracao == geracao_da_thread
    assert not viva
    assert m.estado["trials"] == []


def test_nova_geracao_a_cada_troca(banco):
    m = opt.Mineracao()
    marcos = []
    for _ in range(3):
        m.esquecer()
        marcos.append(m._geracao)
    assert marcos == sorted(set(marcos))   # sempre cresce, nunca repete


# --------------------------------- carregar mineracao salva de volta na tela
def test_lista_so_traz_a_estrategia_ativa(banco):
    """Varredura de outra estratégia não aparece: os parâmetros dela não
    existem nos campos, e abri-la ali só produziria confusão."""
    mineracao_pronta("setup_cruzamento")._persistir("do cruzamento")
    mineracao_pronta("rompimento_canal")._persistir("do rompimento")

    so_cruz = opt.listar_salvas("setup_cruzamento")
    so_romp = opt.listar_salvas("rompimento_canal")

    assert [r["run_id"] for r in so_cruz] == [1]
    assert [r["run_id"] for r in so_romp] == [2]
    assert "cruzamento" in so_cruz[0]["rotulo"]
    assert so_romp[0]["estrategia"] == "rompimento_canal"
    assert len(opt.listar_salvas()) == 2      # sem filtro, vêm as duas


def test_detalhes_trazem_estrategia_perfil_e_espaco(banco):
    m = mineracao_pronta("setup_cruzamento")
    m._contexto["perfil"] = {"timeframe": "M15", "alvo_pontos": 800,
                             "corretagem_por_contrato": 0.5}
    m._persistir("com perfil")

    d = opt.detalhes_salva(1)
    assert d["estrategia"] == "setup_cruzamento"
    assert d["nome"] == "com perfil"
    assert d["perfil"]["timeframe"] == "M15"      # o perfil volta inteiro
    assert d["perfil"]["alvo_pontos"] == 800
    assert d["espaco"]["media_rapida"] == [5, 6, 7, 8, 9]
    assert d["holdout_de"].startswith("2025-")     # data, não "None"


def test_detalhes_de_run_inexistente(banco):
    assert opt.detalhes_salva(999) is None


# ------------------------------------------- espaco -> faixas de/passo/ate
def test_espaco_volta_como_faixa_marcada():
    f = opt.faixas_do_espaco({"media_rapida": [5, 10, 15, 20]})["media_rapida"]
    assert f == {"on": True, "valor": 5, "de": 5, "ate": 20, "passo": 5}


def test_parametro_de_valor_unico_volta_desmarcado():
    """Não foi minerado: volta como valor fixo, sem faixa e sem interruptor."""
    f = opt.faixas_do_espaco({"stop_pontos": [300]})["stop_pontos"]
    assert f == {"on": False, "valor": 300}


def test_grade_irregular_usa_o_menor_passo():
    """Passo irregular ainda tem que cobrir a faixa inteira ao reexecutar."""
    f = opt.faixas_do_espaco({"p": [10, 20, 25, 40]})["p"]
    assert f["on"] and f["de"] == 10 and f["ate"] == 40
    assert f["passo"] == 5          # o menor, para não pular nenhum ponto


def test_espaco_vazio_nao_quebra():
    assert opt.faixas_do_espaco({}) == {}
    assert opt.faixas_do_espaco({"p": []})["p"] == {"on": False, "valor": None}


def test_ida_e_volta_do_espaco(banco):
    """Salvar e recarregar tem que reproduzir a mesma varredura."""
    m = mineracao_pronta()
    m._contexto["espaco"] = {"media_rapida": [5, 9, 13, 17],
                             "media_lenta": [40]}
    m._persistir(None)

    espaco = opt.detalhes_salva(1)["espaco"]
    faixas = opt.faixas_do_espaco(espaco)
    schema = {"media_rapida": {"default": 9, "min": 2, "max": 200,
                               "step": 1, "tipo": "int"},
              "media_lenta": {"default": 21, "min": 3, "max": 600,
                              "step": 1, "tipo": "int"}}
    assert opt.montar_espaco(schema, faixas) == {
        "media_rapida": [5, 9, 13, 17], "media_lenta": [40],
    }


# ------------------- o corte do holdout viaja junto com a mineracao
def test_wf_config_e_gravado_e_volta(banco):
    """Sem isto, carregar uma varredura e clicar numa linha recalculava o
    corte do holdout com os valores da TELA. A mesma combinação aparecia com
    R$ 6.165 na tabela (holdout de 6 meses, usado na varredura) e R$ 5.491
    no card (holdout de 12, que estava na tela)."""
    m = mineracao_pronta()
    m._contexto["wf_config"] = {"treino_meses": 6, "teste_meses": 6,
                                "passo_meses": 6, "holdout_meses": 6}
    m._persistir("com wf")

    d = opt.detalhes_salva(1)
    assert d["wf_config"] == {"treino_meses": 6, "teste_meses": 6,
                              "passo_meses": 6, "holdout_meses": 6}
    # o corte gravado vem com hora, não só a data: é ele que o backtest usa
    assert d["corte"].startswith(d["holdout_de"])


def test_run_antiga_sem_wf_config_deriva_dos_folds(banco):
    """Varreduras salvas antes da coluna existir não podem ficar sem corte."""
    m = mineracao_pronta()
    m._contexto["wf_config"] = {}
    m._persistir(None)
    with db.connect() as con:
        con.execute("UPDATE mining_runs SET wf_config = NULL")

    w = opt.detalhes_salva(1)["wf_config"]
    # os folds padrão são 12/3/3
    assert w["treino_meses"] == 12
    assert w["teste_meses"] == 3
    assert w["passo_meses"] == 3


def test_corte_gravado_sobrevive_a_mudanca_de_tela(banco):
    """O retrato é do momento da varredura; mexer na tela depois não reescreve."""
    m = mineracao_pronta()
    m._contexto["wf_config"] = {"treino_meses": 6, "teste_meses": 6,
                                "passo_meses": 6, "holdout_meses": 6}
    m._persistir(None)
    corte_original = opt.detalhes_salva(1)["corte"]

    outra = mineracao_pronta()
    outra._contexto["wf_config"] = {"treino_meses": 12, "teste_meses": 3,
                                    "passo_meses": 3, "holdout_meses": 12}
    outra._persistir(None)

    assert opt.detalhes_salva(1)["corte"] == corte_original
    assert opt.detalhes_salva(1)["wf_config"]["holdout_meses"] == 6
    assert opt.detalhes_salva(2)["wf_config"]["holdout_meses"] == 12


def test_criterios_de_aceite_sao_gravados_e_voltam(banco):
    """O walk-forward aplica os critérios da mineração dentro de cada janela
    IS. Eles viviam só na tela — salvar agora os grava junto."""
    m = mineracao_pronta()
    crit = {"trades": 300, "pf": 1.25, "fr": 2.0, "consistencia": 60,
            "mediana": 0, "dd": 2500, "lucro": 0}
    m._persistir("com criterios", crit)
    assert opt.detalhes_salva(1)["criterios"] == crit


def test_run_antiga_sem_criterios_volta_none(banco):
    m = mineracao_pronta()
    m._persistir("sem criterios")
    assert opt.detalhes_salva(1)["criterios"] is None


def test_walk_forward_usa_os_criterios_gravados_ou_os_padroes():
    from core import mineracao_stats as MS
    from core import wfa
    from ui.callbacks import _criterios_wfa

    e = {"de": "2021-03-16", "ate_holdout": "2025-03-13 23:59:59"}      # 48 meses
    j = wfa.montar_janelas("2021-03-01", "2025-03-01", 12, 6)[0]

    crit, origem = _criterios_wfa({"criterios": {"trades": 480, "pf": 1.5}}, e)
    assert origem == "critérios da mineração"
    assert crit(j) == {"trades": 120, "pf": 1.5}          # 480 × 12/48

    crit, origem = _criterios_wfa({"criterios": None}, e)
    assert origem == "critérios padrão"
    padrao = {c["id"]: c["padrao"] for c in MS.CRITERIOS}
    assert crit(j)["pf"] == padrao["pf"]
    assert crit(j)["trades"] == max(30, -(-padrao["trades"] * 12 // 48))


# ------------------------------------------- garantias da revisão do banco
def test_excluir_mineracao_leva_os_trades_do_walk_forward_junto(banco):
    """Apagava `wfa_runs` e esquecia `wfa_trades`: 551 órfãos na #40."""
    m = mineracao_pronta()
    m._persistir("com wfa")
    with db.connect_write() as con:
        con.execute("INSERT INTO wfa_runs (wfa_id, run_id, strategy) VALUES (7, 1, 'x')")
        con.execute("INSERT INTO wfa_trades (wfa_id, n, liquido) VALUES (7, 1, 10.0), (7, 2, -3.0)")
    opt.excluir_salva(1)
    with db.connect(read_only=True) as con:
        sobras = [con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("mining_runs", "mining_trials", "wfa_runs", "wfa_trades")]
    assert sobras == [0, 0, 0, 0]


def test_gravacao_que_falha_no_meio_nao_deixa_mineracao_pela_metade(banco, monkeypatch):
    """Sem transação, o run ficava 'concluida' com parte das combinações."""
    def quebra(con, run_id, linhas):
        con.execute("INSERT INTO mining_trials (run_id, trial_id) VALUES (?, 0)", [run_id])
        raise RuntimeError("processo morreu aqui")
    monkeypatch.setattr(opt, "_inserir_trials", quebra)
    m = mineracao_pronta()
    m._persistir("vai falhar")
    assert "falhou" in m.estado["aviso_salvar"]
    assert contar(banco) == (0, 0)


def test_saneamento_marca_gravacao_antiga_incompleta(banco):
    m = mineracao_pronta()
    m._persistir("inteira")
    with db.connect_write() as con:                 # simula a gravação de antes
        con.execute("DELETE FROM mining_trials WHERE trial_id >= 2")
    assert opt.sanear_runs_orfas() == 1
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT status FROM mining_runs").fetchone()[0] == "incompleta"


def test_gravacao_em_lote_e_rapida(banco):
    """executemany levava ~9 ms por combinação; 20 mil levariam 3 minutos."""
    import time
    m = mineracao_pronta()
    m._resultados = [resultado(i, float(i)) for i in range(20_000)]
    t = time.perf_counter()
    m._persistir("grande")
    assert time.perf_counter() - t < 15
    assert contar(banco) == (1, 20_000)


def test_leitura_espera_a_gravacao_em_vez_de_quebrar(banco):
    """No mesmo processo o DuckDB recusa leitura com um escritor aberto."""
    import threading
    import time
    escritor = db.connect()
    solta = threading.Timer(0.6, escritor.close)
    solta.start()
    t = time.perf_counter()
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT 1").fetchone()[0] == 1
    assert time.perf_counter() - t >= 0.4
    solta.join()


def test_recriar_tabela_vazia_nao_quebra_com_ponto_e_virgula_em_comentario(banco):
    with db.connect_write() as con:
        con.execute("DROP TABLE mining_trials")
        con.execute("CREATE TABLE mining_trials (run_id BIGINT, outra VARCHAR)")
        db.init_schema(con)                           # recria pelo schema.sql
        cols = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'mining_trials'").fetchall()]
    assert "score_robusto" in cols and "outra" not in cols


def test_coluna_em_outra_ordem_nao_derruba_a_subida(banco):
    """A comparação levava a ORDEM em conta: uma tabela com dados e as mesmas
    colunas em outra posição fazia o init_schema levantar erro — e ele roda
    em toda subida do app."""
    m = mineracao_pronta()
    m._persistir("com dados")
    with db.connect_write() as con:
        cols = [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'mining_runs' ORDER BY ordinal_position").fetchall()]
        invertidas = ", ".join(reversed(cols))
        con.execute(f"CREATE TABLE mr2 AS SELECT {invertidas} FROM mining_runs")
        con.execute("DROP TABLE mining_runs")
        con.execute("ALTER TABLE mr2 RENAME TO mining_runs")
        db.init_schema(con)                           # não pode levantar
    assert contar(banco) == (1, 5)
