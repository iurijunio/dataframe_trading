"""Fase demo, contratos da conta e Envio de ordens (parte 4, tarefa 12).

São os controles do usuário sobre ordens de verdade: cada recusa e cada
efeito (banco, diário, arquivo de comando) tem o seu teste."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ao_vivo as AV  # noqa: E402
from core import codigo, comandos, diario, engine  # noqa: E402
from core import db_manager as db  # noqa: E402
from core.engine.execution import ExecutionProfile  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401
from tests.fabrica_ao_vivo import ligacao_com_plano  # noqa: E402

PARAMS = {"periodo_canal": 20, "folga_ticks": 0, "filtro_amplitude": 0}
DIA = date(2026, 10, 5)


def _montar(nome="v", *, stop_tipo="pontos", stop_pontos=300, contratos=3,
            limite=500.0, com_conta=True, run_id=1):
    perfil = ExecutionProfile(timeframe="M5", stop_tipo=stop_tipo,
                              stop_pontos=stop_pontos).to_config()
    f = ligacao_com_plano(nome, params=PARAMS, profile=perfil,
                          contratos=contratos, run_id=run_id)
    conta = None
    if com_conta:
        conta = AV.criar_conta(f"demo-{nome}", "demo", limite)
        AV.definir_contas(f.pf, conta, None)
    return f, conta


def _fase(lig):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT fase, fase_desde FROM portfolio_membros "
                           "WHERE ligacao_id = ?", [lig]).fetchone()


def _comandos():
    pasta = Path(comandos.PASTA)
    if not pasta.exists():
        return []
    return [json.loads(a.read_text(encoding="utf-8"))
            for a in sorted(pasta.glob("*.json"))]


def _conferencia(lig, plano_id, estrategia, *, ok, hash_=..., motor=...):
    """Um pregão conferido do papel e a linha do papel × backtest."""
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO papel_pregoes (ligacao_id, dia, plano_id, "
            "codigo_hash, motor_versao, status) VALUES (?,?,?,?,?,'conferido')",
            [lig, DIA, plano_id,
             codigo.hash_estrategia(estrategia) if hash_ is ... else hash_,
             engine.VERSAO if motor is ... else motor])
        con.execute(
            "INSERT INTO papel_backtest (ligacao_id, dia, conferido_em, ok, "
            "n_papel, n_backtest, diferencas) VALUES (?,?,?,?,1,1,?)",
            [lig, DIA, datetime(2026, 10, 6, 1), ok,
             json.dumps({"checksum_mudou": False, "operacoes": []})])


# ------------------------------------------------------------ mudar_fase
def test_promover_para_demo_grava_fase_e_evento(banco):
    f, _ = _montar()
    quando = datetime(2026, 10, 8, 9, 30)
    AV.mudar_fase(f.lig, "demo", quando=quando)
    assert _fase(f.lig) == ("demo", quando)
    [e] = diario.eventos(tipo="fase_mudou", ligacao_id=f.lig)
    assert (e["de"], e["para"], e["origem"]) == ("papel", "demo", "usuario")
    assert e["plano_id"] == f.plano_id


def test_promover_sem_conta_demo_no_portfolio_recusa(banco):
    f, _ = _montar(com_conta=False)
    with pytest.raises(ValueError, match="conta demo"):
        AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "papel"
    assert not diario.eventos(tipo="fase_mudou")


def test_promover_com_conta_demo_arquivada_recusa(banco):
    f, conta = _montar()
    AV.arquivar_conta(conta)
    with pytest.raises(ValueError, match="conta demo"):
        AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "papel"


def test_promover_plano_sem_stop_recusa(banco):
    f, _ = _montar(stop_tipo="pontos", stop_pontos=0)
    with pytest.raises(ValueError, match="stop"):
        AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "papel"
    assert not diario.eventos(tipo="fase_mudou")


def test_promover_plano_com_stop_atr_vale(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"


def test_promover_m1_com_atr_nao_e_recusado(banco):
    # o motor foi corrigido (0dfa0db): M1 com ATR deixou de ser risco
    perfil = ExecutionProfile(timeframe="M1", stop_tipo="atr",
                              stop_pontos=0).to_config()
    f = ligacao_com_plano("m1", params=PARAMS, profile=perfil, contratos=1)
    AV.definir_contas(f.pf, AV.criar_conta("d", "demo", 500.0), None)
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"


def test_falha_do_codigo_e_motor_de_hoje_bloqueia(banco):
    f, _ = _montar()
    _conferencia(f.lig, f.plano_id, "rompimento_canal", ok=False)
    with pytest.raises(ValueError, match="diferiu do backtest"):
        AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "papel"
    assert AV.restricoes_para_demo(f.lig)["motivos"]


def test_falha_de_motor_antigo_nao_bloqueia_e_vira_aviso(banco):
    f, _ = _montar()
    _conferencia(f.lig, f.plano_id, "rompimento_canal", ok=False,
                 motor="2025.01.01")
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"
    assert any("diferença" in a
               for a in AV.restricoes_para_demo(f.lig)["avisos"])


def test_falha_de_codigo_antigo_nao_bloqueia(banco):
    f, _ = _montar()
    _conferencia(f.lig, f.plano_id, "rompimento_canal", ok=False,
                 hash_="0" * 16)
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"


def test_pregao_conferido_igual_ao_backtest_deixa_promover(banco):
    f, _ = _montar()
    _conferencia(f.lig, f.plano_id, "rompimento_canal", ok=True)
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"
    assert not AV.restricoes_para_demo(f.lig)["avisos"]


def test_sem_pregao_conferido_ainda_deixa_promover_com_aviso(banco):
    f, _ = _montar()
    assert any("nenhum pregão" in a
               for a in AV.restricoes_para_demo(f.lig)["avisos"])
    AV.mudar_fase(f.lig, "demo")
    assert _fase(f.lig)[0] == "demo"


def test_voltar_para_papel_nao_exige_nada(banco):
    f, conta = _montar()
    AV.mudar_fase(f.lig, "demo")
    AV.editar_conta(conta, limite_perda_dia=None)
    AV.arquivar_conta(conta)
    AV.mudar_fase(f.lig, "papel")
    assert _fase(f.lig)[0] == "papel"
    de_para = [(e["de"], e["para"])
               for e in diario.eventos(tipo="fase_mudou", ligacao_id=f.lig)]
    assert sorted(de_para) == [("demo", "papel"), ("papel", "demo")]


def test_mudar_para_a_fase_atual_nao_gera_evento(banco):
    f, _ = _montar()
    AV.mudar_fase(f.lig, "papel")
    assert not diario.eventos(tipo="fase_mudou")


def test_fase_real_ainda_nao_existe(banco):
    f, _ = _montar()
    with pytest.raises(ValueError, match="conta real ainda não disponível"):
        AV.mudar_fase(f.lig, "real")
    with pytest.raises(ValueError, match="fase"):
        AV.mudar_fase(f.lig, "qualquer")


def test_fase_de_ligacao_inexistente_recusa(banco):
    with pytest.raises(ValueError, match="não existe"):
        AV.mudar_fase(999, "papel")


# ----------------------------------------------------- definir_contratos
def _contratos(lig):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT contratos_demo FROM portfolio_membros "
                           "WHERE ligacao_id = ?", [lig]).fetchone()[0]


def test_definir_contratos_grava_e_registra(banco):
    f, _ = _montar()
    AV.definir_contratos(f.lig, 2)
    assert _contratos(f.lig) == 2
    [e] = diario.eventos(tipo="contratos_alterados", ligacao_id=f.lig)
    assert (e["de"], e["para"], e["motivo"]) == ("plano", "2", "demo")


def test_definir_contratos_none_volta_ao_plano(banco):
    f, _ = _montar()
    AV.definir_contratos(f.lig, 2)
    AV.definir_contratos(f.lig, None)
    assert _contratos(f.lig) is None
    ultimo = diario.eventos(tipo="contratos_alterados", ligacao_id=f.lig)[-1]
    assert {(ultimo["de"], ultimo["para"])} <= {("2", "plano"), ("plano", "2")}
    assert len(diario.eventos(tipo="contratos_alterados")) == 2


@pytest.mark.parametrize("invalido", [0, -1, 1.5, True, "2"])
def test_definir_contratos_invalido_recusa(banco, invalido):
    f, _ = _montar()
    with pytest.raises(ValueError, match="contratos"):
        AV.definir_contratos(f.lig, invalido)
    assert _contratos(f.lig) is None
    assert not diario.eventos(tipo="contratos_alterados")


def test_definir_contratos_repetido_nao_gera_evento(banco):
    f, _ = _montar()
    AV.definir_contratos(f.lig, 2)
    AV.definir_contratos(f.lig, 2)
    assert len(diario.eventos(tipo="contratos_alterados")) == 1


def test_definir_contratos_so_demo_por_enquanto(banco):
    f, _ = _montar()
    with pytest.raises(ValueError, match="real"):
        AV.definir_contratos(f.lig, 2, tipo="real")


# ------------------------------------------------------------ ligar_envio
def _envio(conta):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT envio_ligado FROM contas WHERE conta_id = ?",
                           [conta]).fetchone()[0]


def test_ligar_envio_sem_limite_recusa(banco):
    conta = AV.criar_conta("sem-limite", "demo")
    with pytest.raises(ValueError, match="limite de perda do dia"):
        AV.ligar_envio(conta, True)
    assert not _envio(conta)
    assert not diario.eventos(tipo="envio_ligado")
    assert _comandos() == []


def test_ligar_envio_com_limite_grava_evento_e_comando(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    assert _envio(conta) is True
    assert len(diario.eventos(tipo="envio_ligado", conta_id=conta)) == 1
    [cmd] = _comandos()
    assert (cmd["tipo"], cmd["conta_id"], cmd["ligado"]) == ("envio", conta, True)


def test_desligar_envio_grava_evento_e_comando(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    for a in Path(comandos.PASTA).glob("*.json"):
        a.unlink()
    AV.ligar_envio(conta, False)
    assert _envio(conta) is False
    assert len(diario.eventos(tipo="envio_desligado", conta_id=conta)) == 1
    [cmd] = _comandos()
    assert (cmd["tipo"], cmd["conta_id"], cmd["ligado"]) == ("envio", conta, False)


def test_desligar_escreve_o_comando_antes_do_banco(banco, monkeypatch):
    # com o banco ocupado (uma mineração segurando a escrita) o desligar
    # ainda precisa chegar à captura
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    for a in Path(comandos.PASTA).glob("*.json"):
        a.unlink()

    def ocupado(*a, **k):  # tentativas/espera do ligar_envio
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", ocupado)
    with pytest.raises(RuntimeError, match="ocupado"):
        AV.ligar_envio(conta, False)
    [cmd] = _comandos()
    assert cmd["ligado"] is False and cmd["conta_id"] == conta


def test_ligar_envio_nao_escreve_comando_se_o_banco_falha(banco, monkeypatch):
    conta = AV.criar_conta("c", "demo", 500.0)

    def ocupado(*a, **k):  # tentativas/espera do ligar_envio
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", ocupado)
    with pytest.raises(RuntimeError):
        AV.ligar_envio(conta, True)
    assert _comandos() == []


def test_ligar_envio_de_conta_inexistente_recusa(banco):
    with pytest.raises(ValueError, match="não existe"):
        AV.ligar_envio(999, True)


def test_ligar_envio_de_conta_arquivada_recusa(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.arquivar_conta(conta)
    with pytest.raises(ValueError, match="arquivada"):
        AV.ligar_envio(conta, True)
    assert _comandos() == []


def test_ligar_envio_ja_ligado_nao_repete_evento(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    AV.ligar_envio(conta, True)
    assert len(diario.eventos(tipo="envio_ligado")) == 1


# ------------------------------------------- editar_conta apaga o limite
@pytest.mark.parametrize("vazio", [None, 0])
def test_apagar_limite_com_envio_ligado_desliga_o_envio(banco, vazio):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    for a in Path(comandos.PASTA).glob("*.json"):
        a.unlink()
    AV.editar_conta(conta, limite_perda_dia=vazio)
    assert _envio(conta) is False
    [e] = diario.eventos(tipo="envio_desligado", conta_id=conta)
    assert e["motivo"] == "limite apagado"
    [cmd] = _comandos()
    assert (cmd["tipo"], cmd["conta_id"], cmd["ligado"]) == ("envio", conta, False)


def test_apagar_limite_com_envio_desligado_nao_mexe_no_envio(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.editar_conta(conta, limite_perda_dia=None)
    assert not diario.eventos(tipo="envio_desligado")
    assert _comandos() == []


def test_mudar_o_limite_para_outro_valor_mantem_o_envio(banco):
    conta = AV.criar_conta("c", "demo", 500.0)
    AV.ligar_envio(conta, True)
    AV.editar_conta(conta, limite_perda_dia=800.0)
    assert _envio(conta) is True
    assert not diario.eventos(tipo="envio_desligado")


# ------------------------------------------------------ custo_de_um_stop
def test_custo_de_um_stop_em_pontos(banco):
    # 300 pontos x 3 contratos x R$ 0,20 = R$ 180 = 36% de R$ 500
    f, _ = _montar(stop_pontos=300)
    r = AV.custo_de_um_stop(f.lig, 3)
    assert r["reais"] == pytest.approx(180.0)
    assert r["pct_limite"] == pytest.approx(36.0)


def test_custo_de_um_stop_sem_conta_demo_nao_tem_percentual(banco):
    f, _ = _montar(com_conta=False)
    r = AV.custo_de_um_stop(f.lig, 3)
    assert r["reais"] == pytest.approx(180.0) and r["pct_limite"] is None


def test_custo_de_um_stop_sem_limite_nao_tem_percentual(banco):
    f, _ = _montar(limite=None)
    assert AV.custo_de_um_stop(f.lig, 1)["pct_limite"] is None


def _op_papel(lig, plano_id, n, entry, stop_ini, stop_fim=None):
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
            "entry_ts, side, contratos, entry_px, stop_px, stop_ini_px, "
            "aberta, conta, calculado_em) VALUES (nextval('seq_papel_op'), "
            "?, ?, ?, ?, 1, 1, ?, ?, ?, false, true, ?)",
            [lig, plano_id, DIA, datetime(2026, 10, 5, 10, n), entry,
             stop_fim if stop_fim is not None else stop_ini, stop_ini,
             datetime(2026, 10, 5, 19)])


def test_custo_de_um_stop_atr_usa_a_mediana_do_stop_da_entrada(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    for n, dist in enumerate((100, 200, 900)):
        _op_papel(f.lig, f.plano_id, n, 120_000, 120_000 - dist)
    r = AV.custo_de_um_stop(f.lig, 2)          # mediana 200 x 2 x 0,20
    assert r["reais"] == pytest.approx(80.0)
    assert r["pct_limite"] == pytest.approx(16.0)


def test_custo_atr_ignora_o_stop_que_andou_para_o_breakeven(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    # stop final no preço de entrada (breakeven): distância 0 não vale
    for n in range(3):
        _op_papel(f.lig, f.plano_id, n, 120_000, 119_800, stop_fim=120_000)
    assert AV.custo_de_um_stop(f.lig, 2)["reais"] == pytest.approx(80.0)


def test_custo_atr_ignora_operacoes_de_outro_plano(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    _op_papel(f.lig, f.plano_id, 0, 120_000, 119_800)
    for n in (1, 2, 3):
        _op_papel(f.lig, f.plano_id + 99, n, 120_000, 118_000)
    assert AV.custo_de_um_stop(f.lig, 2)["reais"] == pytest.approx(80.0)


def test_custo_de_um_stop_atr_sem_operacao_no_papel_e_none(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    assert AV.custo_de_um_stop(f.lig, 2) == {"reais": None, "pct_limite": None}


def test_custo_atr_operacao_sem_stop_inicial_nao_conta(banco):
    f, _ = _montar(stop_tipo="atr", stop_pontos=0)
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
            "entry_ts, side, contratos, entry_px, stop_px, aberta, conta, "
            "calculado_em) VALUES (nextval('seq_papel_op'), ?, ?, ?, ?, 1, 1, "
            "120000, 119000, false, true, ?)",
            [f.lig, f.plano_id, DIA, datetime(2026, 10, 5, 10, 1),
             datetime(2026, 10, 5, 19)])
    assert AV.custo_de_um_stop(f.lig, 2)["reais"] is None


@pytest.mark.parametrize("invalido", [0, -1, 1.5, True, "2"])
def test_custo_de_um_stop_contratos_invalido_recusa(banco, invalido):
    f, _ = _montar()
    with pytest.raises(ValueError, match="contratos"):
        AV.custo_de_um_stop(f.lig, invalido)


def test_custo_de_um_stop_ignora_conta_demo_arquivada(banco):
    f, conta = _montar()
    AV.arquivar_conta(conta)
    r = AV.custo_de_um_stop(f.lig, 3)
    assert r["reais"] == pytest.approx(180.0) and r["pct_limite"] is None


# --------------------------------------------- stop ATR vazio, limite < 0
def test_atr_com_multiplicador_zero_nao_conta_como_stop(banco):
    perfil = ExecutionProfile(timeframe="M5", stop_tipo="atr", stop_pontos=0,
                              stop_atr_mult=0.0).to_config()
    f = ligacao_com_plano("atr0", params=PARAMS, profile=perfil, contratos=1)
    AV.definir_contas(f.pf, AV.criar_conta("d", "demo", 500.0), None)
    with pytest.raises(ValueError, match="stop"):
        AV.mudar_fase(f.lig, "demo")


def test_limite_negativo_recusa_ao_criar_e_ao_editar(banco):
    with pytest.raises(ValueError, match="negativo"):
        AV.criar_conta("neg", "demo", -100.0)
    conta = AV.criar_conta("c", "demo", 500.0)
    with pytest.raises(ValueError, match="negativo"):
        AV.editar_conta(conta, limite_perda_dia=-1)
    assert AV.listar_contas()[0]["limite_perda_dia"] == 500.0


def test_ligar_envio_conta_arquivada_sem_limite_diz_arquivada(banco):
    conta = AV.criar_conta("c", "demo")
    AV.arquivar_conta(conta)
    with pytest.raises(ValueError, match="arquivada"):
        AV.ligar_envio(conta, True)
