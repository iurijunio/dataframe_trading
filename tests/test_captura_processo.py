"""O processo da captura com MT5 e relógio falsos (sem terminal de verdade)."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import captura as P  # noqa: E402
from core import captura as C  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from tests.test_ingest import write_export  # noqa: E402

_DT = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
       ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")]


def _epoch(ts):
    return int(ts.replace(tzinfo=timezone.utc).timestamp())


class MT5Falso:
    TIMEFRAME_M1 = 1

    def __init__(self, minutos, tick, conectado=True, aberto=True):
        self.minutos, self.tick = minutos, tick
        self.conectado, self.aberto = conectado, aberto
        self.inits = 0
        self.init_kwargs = []

    def initialize(self, path=None, **kwargs):
        self.inits += 1
        self.init_kwargs.append(kwargs)
        return self.aberto

    def terminal_info(self):
        return SimpleNamespace(connected=self.conectado) if self.aberto else None

    def symbol_select(self, s, on):
        return s == "WIN$N"

    def account_info(self):
        return SimpleNamespace(login=123, server="Srv-DEMO")

    def symbol_info(self, s):
        return SimpleNamespace(basis="WINV26")

    def symbol_info_tick(self, s):
        return SimpleNamespace(time=_epoch(self.tick))

    def copy_rates_range(self, s, tf, desde, ate):
        d, a = desde.replace(tzinfo=None), ate.replace(tzinfo=None)
        linhas = [(_epoch(t), 100000, 100050, 99950, 100010, 50, 5, 0)
                  for t in self.minutos if d <= t <= a]
        return np.array(linhas, dtype=_DT) if linhas else None

    def shutdown(self):
        pass


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PARQUET_DIR", tmp_path / "parquet")
    with db.connect_write() as con:
        db.init_schema(con)
        db.sync_instruments(con)
        ing.ingest_csv(con, write_export(tmp_path / "s.tsv", [
            (datetime(2026, 9, 30, 18, 24), 100000, 100050, 99950, 100010)]), "WIN$N")
    return tmp_path


class Mono:
    """monotonic controlado pelo teste"""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _servico(mt5, agora, pasta, mono=None):
    return P.Servico(mt5=mt5, agora=lambda: agora, mono=mono or Mono(), pasta=pasta,
                     terminal_aberto=lambda: True)


def _minutos(inicio, n):
    return [inicio + timedelta(minutes=i) for i in range(n)]


def test_volta_grava_os_fechados_e_publica_o_em_formacao(base):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")

    s.volta()

    with db.connect(read_only=True) as con:
        assert con.execute("SELECT max(ts) FROM bars_m1").fetchone()[0] == datetime(2026, 10, 1, 9, 4)
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["mt5"] == "conectado" and e["em_formacao"]["ts"] == "2026-10-01T09:05:00"
    assert e["ultimo_salvo"] == "2026-10-01T09:04:00" and e["gravados_hoje"] == 5


def test_banco_ocupado_nao_avanca_e_a_volta_seguinte_grava_sem_duplicar(base, monkeypatch):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    real = db.connect_write
    monkeypatch.setattr(db, "connect_write", lambda **k: (_ for _ in ()).throw(RuntimeError("ocupado")))
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["banco_ocupado_desde"] is not None and e["ultimo_salvo"] == "2026-09-30T18:24:00"

    monkeypatch.setattr(db, "connect_write", real)
    s.volta()
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT count(*) FROM bars_m1").fetchone()[0] == 6


def test_mt5_fechado_nao_inicializa_e_avisa(base):
    agora = datetime(2026, 10, 1, 10, 0)
    mt5 = MT5Falso([], tick=agora, aberto=False)
    s = P.Servico(mt5=mt5, agora=lambda: agora, mono=Mono(), pasta=base / "ao_vivo",
                  terminal_aberto=lambda: False)
    s.volta()
    assert mt5.inits == 0
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["mt5"] == "fechado"


def test_sem_conexao_com_a_corretora(base):
    agora = datetime(2026, 10, 1, 10, 0)
    s = _servico(MT5Falso([], tick=agora, conectado=False), agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["mt5"] == "sem_conexao" and e["mt5_desde"] == "2026-10-01T10:00:00"


def test_simbolo_ausente_e_erro_de_configuracao(base):
    agora = datetime(2026, 10, 1, 10, 0)
    s = P.Servico(mt5=MT5Falso([], tick=agora), simbolo="XXX$N", agora=lambda: agora,
                  mono=Mono(), pasta=base / "ao_vivo", terminal_aberto=lambda: True)
    with pytest.raises(P.ErroDeConfiguracao):
        s.volta()


def test_mt5_sem_o_simbolo_e_erro_de_configuracao(base):
    # o teste acima também cairia por falta de YAML/base do XXX$N; aqui só
    # o MT5 recusa o símbolo — três voltas seguidas, para não confundir com
    # o terminal que ainda está carregando a lista logo após o login
    agora = datetime(2026, 10, 1, 10, 0)
    mt5 = MT5Falso([], tick=agora)
    mt5.symbol_select = lambda s, on: False
    s = _servico(mt5, agora, base / "ao_vivo")
    for _ in range(P.FALHAS_SIMBOLO - 1):
        s.volta()
        assert C.ler_estado(base / "ao_vivo" / "estado.json")["mt5"] == "sem_conexao"
    with pytest.raises(P.ErroDeConfiguracao, match="não tem WIN\\$N"):
        s.volta()


def test_symbol_select_falhando_uma_vez_apos_o_login_nao_para_a_captura(base):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    respostas = [False, False, True, False, False, True]
    mt5.symbol_select = lambda s, on: respostas.pop(0)
    s = _servico(mt5, agora, base / "ao_vivo")
    s.volta()
    s.volta()
    s.volta()            # deu certo: a contagem recomeça
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["mt5"] == "conectado" and e["gravados_hoje"] == 5
    # nova conexão (terminal reaberto): duas falhas ainda não são configuração
    s.conectado = False
    s.volta()
    s.volta()
    s.volta()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["mt5"] == "conectado"


def test_initialize_tem_timeout_curto(base):
    agora = datetime(2026, 10, 1, 10, 0)
    mt5 = MT5Falso([], tick=agora)
    _servico(mt5, agora, base / "ao_vivo").volta()
    assert mt5.init_kwargs == [{"timeout": 10_000}]


def test_price_decimals_vem_do_yaml(base, monkeypatch):
    real = db.load_instrument_yaml
    monkeypatch.setattr(db, "load_instrument_yaml",
                        lambda s: {**real(s), "price_decimals": 2})
    s = P.Servico(mt5=MT5Falso([], tick=datetime(2026, 10, 1)), pasta=base / "ao_vivo")
    assert s.price_decimals == 2


def _conferencia_falhando(mt5):
    """O MT5 falha só na releitura do dia inteiro (00:00 → 23:59)."""
    original = mt5.copy_rates_range
    chamadas = []

    def falso(s, tf, desde, ate):
        if ate - desde == timedelta(hours=23, minutes=59):
            chamadas.append(desde)
            raise RuntimeError("terminal não respondeu")
        return original(s, tf, desde, ate)
    mt5.copy_rates_range = falso
    return chamadas


def test_conferencia_que_falha_no_mt5_espera_a_janela_de_5_min(base):
    agora = datetime(2026, 10, 1, 18, 40)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                   tick=datetime(2026, 10, 1, 18, 24))
    chamadas = _conferencia_falhando(mt5)
    mono = Mono()
    s = _servico(mt5, agora, base / "ao_vivo", mono)
    s.volta()
    assert len(chamadas) == 1
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] == "falhou"

    mono.t += 1          # a volta seguinte, 1 s depois
    s.volta()
    assert len(chamadas) == 1

    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert len(chamadas) == 2


def test_conferencia_vence_a_captura_mesmo_com_o_pc_atrasado(base):
    # PC 5 min atrás do servidor: a marca da conferência sai da hora do
    # servidor, não do relógio do PC
    agora = datetime(2026, 10, 1, 18, 40)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                   tick=datetime(2026, 10, 1, 18, 45))
    s = _servico(mt5, agora, base / "ao_vivo")
    s.volta()
    with db.connect(read_only=True) as con:
        marca = con.execute("SELECT source_max_ts FROM ingest_log WHERE "
                            "source_file = 'conferencia://2026-10-01'").fetchone()[0]
    assert marca == datetime(2026, 10, 1, 18, 46)

    # PC adiantado: vale o próprio PC, mais 1 min
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 2, 9, 0), 3),
                   tick=datetime(2026, 10, 2, 18, 24))
    s = _servico(mt5, datetime(2026, 10, 2, 18, 40), base / "ao_vivo")
    s.volta()
    with db.connect(read_only=True) as con:
        marca = con.execute("SELECT source_max_ts FROM ingest_log WHERE "
                            "source_file = 'conferencia://2026-10-02'").fetchone()[0]
    assert marca == datetime(2026, 10, 2, 18, 41)


def test_depois_do_fechamento_confere_o_dia_e_exporta_o_parquet(base):
    dia = _minutos(datetime(2026, 10, 1, 9, 0), 3)
    agora = datetime(2026, 10, 1, 18, 40)
    s = _servico(MT5Falso(dia, tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "concluida"
    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 4


def test_reinicio_nao_zera_o_placar_do_dia(base):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    _servico(mt5, agora, base / "ao_vivo").volta()
    _servico(mt5, agora + timedelta(seconds=5), base / "ao_vivo").volta()   # reabriu
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["gravados_hoje"] == 5


def test_erro_passageiro_some_na_volta_seguinte(base, monkeypatch):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    original = mt5.copy_rates_range
    mt5.copy_rates_range = lambda *a: (_ for _ in ()).throw(RuntimeError("falha do terminal"))
    s.passo_seguro()                       # o que o rodar() faz a cada volta
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["erro"] == "falha do terminal"
    mt5.copy_rates_range = original
    s.passo_seguro()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["erro"] is None


def test_mercado_ainda_aberto_apos_o_fechamento_esperado_nao_confere(base):
    # troca de horário dos EUA: a moda diz 17:54, mas o mercado vai até 18:24
    agora = datetime(2026, 10, 1, 18, 5)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 17, 50), 15), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    s.fechamento = time(17, 54)           # como se o histórico dissesse 17:54
    s.volta()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] != "concluida"


def test_estado_preso_pela_tela_nao_para_a_gravacao(base, monkeypatch):
    # escrever_estado desiste com PermissionError se a tela segurar o arquivo
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo")
    monkeypatch.setattr(C, "escrever_estado",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("em uso")))
    assert s.volta() == 1
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT max(ts) FROM bars_m1").fetchone()[0] == datetime(2026, 10, 1, 9, 4)


def test_dia_que_o_mt5_nao_devolve_fica_pendente_e_os_outros_seguem(base):
    from core.mt5_source import barras_de_taxas
    d29, d30 = datetime(2026, 9, 29, 10, 0), datetime(2026, 9, 30, 10, 0)
    antigos = MT5Falso([d29, d30], tick=d30)
    with db.connect_write() as con:
        C.gravar(con, "WIN$N", barras_de_taxas(antigos.copy_rates_range("WIN$N", 1, d29, d30)),
                 C.origem_captura(1, "x"))
    agora = datetime(2026, 10, 1, 10, 0)
    s = _servico(MT5Falso([d30], tick=agora), agora, base / "ao_vivo")   # 29/09 sumiu do MT5

    s.volta()

    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "falhou" and "29/09/2026" in e["conferencia"]["erro"]
    assert e["conferencia"]["dias"] == ["2026-09-30"] and e["erro"] is None
    with db.connect(read_only=True) as con:
        assert C.dias_pendentes(con, "WIN$N", agora.date(), False) == [d29.date()]


def _export_falha_uma_vez(monkeypatch):
    real = db.export_parquet
    chamadas = []

    def falso(con, simbolo):
        chamadas.append(simbolo)
        if len(chamadas) == 1:
            raise PermissionError("pasta do Parquet em uso")
        return real(con, simbolo)
    monkeypatch.setattr(db, "export_parquet", falso)
    return chamadas


def test_parquet_que_falhou_e_refeito_na_janela_seguinte(base, monkeypatch):
    # a linha conferencia:// já foi gravada quando o export falha: o dia sai
    # das pendências, mas o Parquet ainda precisa ser refeito
    _export_falha_uma_vez(monkeypatch)
    agora = datetime(2026, 10, 1, 18, 40)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                          tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo", mono)
    s.volta()
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] == "falhou"

    mono.t += P.A_CADA_CONFERENCIA
    s.volta()

    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "concluida" and e["conferencia"]["dias"] == ["2026-10-01"]
    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 4


def test_parquet_que_falhou_e_refeito_mesmo_depois_de_reabrir(base, monkeypatch):
    _export_falha_uma_vez(monkeypatch)
    agora = datetime(2026, 10, 1, 18, 40)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3), tick=datetime(2026, 10, 1, 18, 24))
    _servico(mt5, agora, base / "ao_vivo").volta()             # export falhou e a captura caiu

    _servico(mt5, agora + timedelta(minutes=1), base / "ao_vivo").volta()   # reabriu

    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] == "concluida"
    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 4


def test_volta_de_dias_desligado_so_conta_o_placar_de_hoje(base):
    agora = datetime(2026, 10, 2, 9, 5, 20)
    minutos = _minutos(datetime(2026, 10, 1, 9, 0), 3) + _minutos(datetime(2026, 10, 2, 9, 0), 6)
    s = _servico(MT5Falso(minutos, tick=agora), agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    # 09:00–09:04 de hoje; 09:00–09:03 começaram há mais de 2 min
    assert e["gravados_hoje"] == 5 and e["recuperados_hoje"] == 4
    _servico(MT5Falso(minutos, tick=agora), agora, base / "ao_vivo").volta()   # reabriu
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["gravados_hoje"] == 5


def test_main_com_outra_instancia_devolve_4_sem_abrir_log(base, monkeypatch):
    monkeypatch.setattr(P, "PASTA", base / "ao_vivo")
    trava = P.travar(base / "ao_vivo" / "captura.lock")
    assert P.main([]) == P.OUTRA_INSTANCIA
    assert not (base / "ao_vivo" / "captura.log").exists()
    trava.close()


def test_segunda_instancia_nao_pega_a_trava(base):
    trava = P.travar(base / "ao_vivo" / "captura.lock")
    assert trava is not None
    assert P.travar(base / "ao_vivo" / "captura.lock") is None
    trava.close()
    assert P.travar(base / "ao_vivo" / "captura.lock") is not None


def test_trava_solta_quando_o_processo_morre_a_forca(tmp_path):
    lock = tmp_path / "captura.lock"
    filho = subprocess.Popen([sys.executable, "-c",
        f"import sys,time; sys.path.insert(0, {str(RAIZ)!r}); import captura as P; "
        f"t=P.travar(__import__('pathlib').Path({str(lock)!r})); print('ok', flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True)
    assert filho.stdout.readline().strip() == "ok"
    assert P.travar(lock) is None
    # o python.exe do .venv é um redirecionador que abre o interpretador de
    # verdade como filho: matar só ele deixaria o filho vivo com a trava
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(filho.pid)],
                   capture_output=True)
    filho.wait()
    assert P.travar(lock) is not None


# ----------------------------------------------------------------- papel
@pytest.fixture
def ligacao(base, monkeypatch):
    """Uma variante com plano em vigor, ligada num portfólio ligado, no
    banco temporário. O reload de verdade re-executaria a estratégia no
    meio da suíte (ver tests/test_papel_motor.py:recargas)."""
    from core import codigo, plano, variantes
    from core import papel
    from core import portfolio as PF
    from tests._cadeia import campos_plano, mineracao, wfa

    monkeypatch.setattr(papel.importlib, "reload", lambda mod: mod)
    v = variantes.criar("romp-captura", "rompimento_canal")
    mineracao(1, variante_id=v)
    wfa(1, 1)
    plano.salvar(**campos_plano(
        params={"periodo_canal": 20, "folga_ticks": 0, "filtro_amplitude": 0},
        codigo_hash=codigo.hash_estrategia("rompimento_canal")),
        agora=datetime(2026, 9, 1, 10))
    lig = PF.adicionar_variante(PF.criar("pf"), v)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = '2026-09-01 09:00'")
        con.execute("UPDATE portfolios SET ligado = true")
    return lig


def _pregao_papel(lig, dia):
    with db.connect(read_only=True) as con:
        return con.execute("SELECT status, motivo FROM papel_pregoes WHERE "
                           "ligacao_id = ? AND dia = ?", [lig, dia]).fetchone()


def _contar(monkeypatch, nome, antes=None):
    """Espiona `core.papel.<nome>`: anota os argumentos e chama o original."""
    from core import papel
    real = getattr(papel, nome)
    chamadas = []

    def espiao(*a, **k):
        chamadas.append(a)
        if antes:
            antes()
        return real(*a, **k)
    monkeypatch.setattr(papel, nome, espiao)
    return chamadas


def test_candle_novo_calcula_e_publica_o_papel(base, ligacao):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo")
    s.volta()

    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"
    p = C.ler_estado(base / "ao_vivo" / "estado.json")["papel"]
    assert p["calculado_em"] == "2026-10-01T09:05:20" and p["pendente"] is False
    assert p["ligacoes"][str(ligacao)] == {"status": "rodando", "motivo": None,
                                           "dia": "2026-10-01"}
    assert p["divergencias"] == 0


def test_volta_sem_candle_novo_nao_recalcula_o_papel(base, ligacao, monkeypatch):
    chamadas = _contar(monkeypatch, "rodar_dia")
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    mono = Mono()
    s = _servico(mt5, agora, base / "ao_vivo", mono)
    s.volta()
    assert len(chamadas) == 1

    mono.t += 1                       # 09:05 ainda em formação: nada novo
    s.volta()
    assert len(chamadas) == 1

    # o 09:05 fechou: candle novo, papel recalculado
    mt5.minutos = _minutos(datetime(2026, 10, 1, 9, 0), 7)
    mt5.tick = depois = datetime(2026, 10, 1, 9, 6, 10)
    s.agora = lambda: depois
    mono.t += 50
    s.volta()
    assert len(chamadas) == 2


def test_banco_ocupado_no_papel_fica_pendente_e_refaz_sem_candle_novo(base, ligacao,
                                                                     monkeypatch):
    real = db.connect_write
    ocupado = {"sim": False}

    def escritor(**k):
        if ocupado["sim"]:
            raise RuntimeError("ocupado")
        return real(**k)
    monkeypatch.setattr(db, "connect_write", escritor)
    # a mineração pega o escritor justo entre o cálculo e a gravação do papel
    chamadas = _contar(monkeypatch, "rodar_dia",
                       antes=lambda: ocupado.update(sim=len(chamadas) == 1))

    agora = datetime(2026, 10, 1, 9, 5, 20)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo", mono)
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["papel"]["pendente"] is True and e["erro"] is None
    assert _pregao_papel(ligacao, agora.date()) is None

    mono.t += 1                       # sem candle novo, mas o papel estava pendente
    s.volta()
    assert len(chamadas) == 2
    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["papel"]["pendente"] is False


def test_falha_no_papel_de_uma_ligacao_nao_derruba_a_volta(base, ligacao, monkeypatch):
    from core import papel
    monkeypatch.setattr(papel, "calcular",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    agora = datetime(2026, 10, 1, 9, 5, 20)
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo")
    assert s.volta() == P.ESPERA_PREGAO

    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["erro"] is None and e["gravados_hoje"] == 5
    lig = e["papel"]["ligacoes"][str(ligacao)]
    assert lig["status"] == "rodando" and "falha no cálculo" in lig["motivo"]


def test_falha_no_papel_inteiro_nao_impede_o_publicar(base, ligacao, monkeypatch):
    from core import papel
    monkeypatch.setattr(papel, "rodar_dia",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("barras")))
    agora = datetime(2026, 10, 1, 9, 5, 20)
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo")
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["erro"] is None and e["ultimo_salvo"] == "2026-10-01T09:04:00"
    assert e["papel"]["calculado_em"] is None and "barras" in e["papel"]["erros"]["calculo"]


def test_conferencia_do_dia_confere_o_papel(base, ligacao, monkeypatch):
    chamadas = _contar(monkeypatch, "conferir")
    agora = datetime(2026, 10, 1, 18, 40)
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                          tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo")
    s.volta()

    assert [a[1] for a in chamadas] == [agora.date()]
    assert _pregao_papel(ligacao, agora.date())[0] == "conferido"
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "concluida"
    assert e["papel"]["ligacoes"][str(ligacao)]["status"] == "conferido"

def _conferir_falhando_uma_vez(monkeypatch, falha):
    """`papel.conferir` falha (ou some, como num processo fechado) só na
    primeira chamada; depois é o de verdade. Devolve os dias pedidos."""
    from core import papel
    real = papel.conferir
    dias = []

    def falso(con, dia, *a, **k):
        dias.append(dia)
        if len(dias) == 1:
            return falha()
        return real(con, dia, *a, **k)
    monkeypatch.setattr(papel, "conferir", falso)
    return dias


def test_papel_que_falhou_na_conferencia_e_conferido_na_janela_seguinte(base, ligacao,
                                                                        monkeypatch):
    dias = _conferir_falhando_uma_vez(
        monkeypatch, lambda: (_ for _ in ()).throw(RuntimeError("motor caiu")))
    agora = datetime(2026, 10, 1, 18, 40)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                          tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo", mono)
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    # os candles estão conferidos (o dia sai das pendências), o papel não
    assert e["conferencia"]["status"] == "concluida"
    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"
    assert "motor caiu" in e["papel"]["erros"]["conferencia"]

    mono.t += 1                       # a janela de 5 min ainda não passou
    s.volta()
    assert len(dias) == 1

    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert dias == [agora.date(), agora.date()]
    assert _pregao_papel(ligacao, agora.date())[0] == "conferido"
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["papel"]["erros"]["conferencia"] is None


def test_dia_conferido_sem_papel_gravado_e_conferido_na_janela_seguinte(base, ligacao,
                                                                        monkeypatch):
    # dia recuperado (PC desligado): a conferência dos candles fez COMMIT e
    # o processo fechou antes do papel — nenhuma linha do dia em papel_pregoes
    d29, d30 = datetime(2026, 9, 29, 10, 0), datetime(2026, 9, 30, 10, 0)
    with db.connect_write() as con:
        from core.mt5_source import barras_de_taxas
        C.gravar(con, "WIN$N", barras_de_taxas(
            MT5Falso([d30], tick=d30).copy_rates_range("WIN$N", 1, d30, d30)),
            C.origem_captura(1, "x"))
        # o papel já existia antes do dia recuperado
        con.execute("INSERT INTO papel_pregoes (ligacao_id, dia, status, "
                    "n_operacoes, liquido, calculado_em) VALUES "
                    "(?, ?, 'conferido', 0, 0, ?)", [ligacao, d29.date(), d29])
    # uma ligação de outro símbolo nunca ganha linha no papel do WIN$N: não
    # pode deixar o dia "por conferir" para sempre
    from core import codigo, plano, variantes
    from core import portfolio as PF
    from tests._cadeia import campos_plano, mineracao, wfa
    v2 = variantes.criar("outro-simbolo", "rompimento_canal")
    mineracao(2, variante_id=v2)
    wfa(2, 2)
    plano.salvar(**campos_plano(wfa_id=2, run_id=2, symbol="WDO$N",
                                codigo_hash=codigo.hash_estrategia("rompimento_canal")),
                 agora=datetime(2026, 9, 1, 10))
    PF.adicionar_variante(PF.criar("pf2"), v2)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = '2026-09-01 09:00'")
    dias = _conferir_falhando_uma_vez(monkeypatch, lambda: [])
    agora = datetime(2026, 10, 1, 8, 0)
    mono = Mono()
    # o MT5 com o dia inteiro (o 18:24 veio da exportação da fixture): a
    # reconferência da janela seguinte deixa o dia idêntico ao MT5 e, sem
    # ele, apagaria o 18:24 e reabriria o papel
    s = _servico(MT5Falso([d30, datetime(2026, 9, 30, 18, 24)], tick=agora), agora,
                 base / "ao_vivo", mono)
    s.volta()
    assert dias == [d30.date()] and _pregao_papel(ligacao, d30.date()) is None

    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert dias == [d30.date(), d30.date()]
    assert _pregao_papel(ligacao, d30.date())[0] == "conferido"

    mono.t += P.A_CADA_CONFERENCIA    # congelado: não é pedido de novo
    s.volta()
    assert len(dias) == 2

# ------------------------------------------------ papel não trava os candles
def test_falha_ao_listar_o_papel_nao_trava_a_conferencia_dos_candles(
        base, ligacao, monkeypatch):
    import duckdb
    chamadas = []

    def quebra(self, con):
        chamadas.append(1)
        raise duckdb.CatalogException("Table with name papel_pregoes does not exist")
    monkeypatch.setattr(P.Servico, "_papel_a_conferir", quebra)
    agora = datetime(2026, 10, 1, 18, 40)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                          tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo", mono)
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    # os candles foram conferidos e o espelho refeito, apesar do papel
    assert e["conferencia"]["status"] == "concluida"
    assert len(db.read_bars_parquet("WIN$N")["ts"]) == 4
    assert "papel_pregoes" in e["papel"]["erros"]["conferencia"]
    assert e["erro"] is None
    # a janela foi gasta: nada de repetir (e de traceback) a cada volta
    n = len(chamadas)
    mono.t += 1
    s.volta()
    assert len(chamadas) == n
    # e a falha não some sozinha enquanto não houver uma janela que dê certo
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["papel"]["erros"][
        "conferencia"]


def test_captura_cria_as_tabelas_do_papel_que_faltam(base, ligacao):
    # banco real de antes da parte 3: o app ainda não subiu com o schema novo
    with db.connect_write() as con:
        con.execute("DROP TABLE papel_operacoes")
        con.execute("DROP TABLE papel_pregoes")
    agora = datetime(2026, 10, 1, 9, 5, 20)
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo")
    s.volta()
    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"


def test_captura_com_banco_ocupado_tenta_o_schema_na_volta_seguinte(
        base, ligacao, monkeypatch):
    with db.connect_write() as con:
        con.execute("DROP TABLE papel_operacoes")
        con.execute("DROP TABLE papel_pregoes")
    real = db.connect_write
    ocupado = {"sim": True}

    def escritor(**k):
        if ocupado["sim"]:
            raise RuntimeError("ocupado")
        return real(**k)
    monkeypatch.setattr(db, "connect_write", escritor)
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora),
                 agora, base / "ao_vivo", mono)
    s.volta()
    ocupado["sim"] = False
    mono.t += 1
    s.volta()
    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"


def test_variante_removida_no_meio_do_pregao_e_encerrada_na_conferencia(
        base, ligacao, monkeypatch):
    agora = datetime(2026, 10, 1, 9, 5, 20)
    mono = Mono()
    mt5 = MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 6), tick=agora)
    s = _servico(mt5, agora, base / "ao_vivo", mono)
    s.volta()
    assert _pregao_papel(ligacao, agora.date())[0] == "rodando"
    # removida às 10h; a captura caiu antes de recalcular
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET removido_em = '2026-10-01 10:00'")
    # a primeira conferência do papel some (processo fechado no meio)
    dias = _conferir_falhando_uma_vez(monkeypatch, lambda: [])
    fim = datetime(2026, 10, 1, 18, 40)
    # sem candle novo: o papel do minuto não roda, só a conferência
    mt5.minutos = _minutos(datetime(2026, 10, 1, 9, 0), 5)
    mt5.tick = datetime(2026, 10, 1, 18, 24)
    s.agora = lambda: fim
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert dias == [agora.date()]
    # a janela seguinte ainda a encontra por conferir — e a encerra
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert dias == [agora.date(), agora.date()]
    assert _pregao_papel(ligacao, agora.date()) == (
        "interrompido", "variante removida do portfólio")
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert len(dias) == 2


def test_variante_removida_antes_do_primeiro_calculo_nao_fica_por_conferir(
        base, ligacao, monkeypatch):
    # o papel já existia (um pregão conferido antes); a variante sai do
    # portfólio às 08:00, antes de qualquer cálculo do dia: não há pregão
    # a encerrar, e o dia não pode voltar à lista a cada janela
    with db.connect_write() as con:
        con.execute("INSERT INTO papel_pregoes (ligacao_id, dia, status, "
                    "n_operacoes, liquido, calculado_em) VALUES "
                    "(?, '2026-09-30', 'conferido', 0, 0, '2026-09-30 18:40')",
                    [ligacao])
        con.execute("UPDATE portfolio_membros SET removido_em = '2026-10-01 08:00'")
    chamadas = _contar(monkeypatch, "conferir")
    agora = datetime(2026, 10, 1, 18, 40)
    mono = Mono()
    s = _servico(MT5Falso(_minutos(datetime(2026, 10, 1, 9, 0), 3),
                          tick=datetime(2026, 10, 1, 18, 24)), agora, base / "ao_vivo", mono)
    s.volta()
    assert len(chamadas) == 1                 # a conferência dos candles do dia
    assert _pregao_papel(ligacao, agora.date()) is None
    # o SQL já descarta o dia: nem chega à regra fina do papel
    finas = _contar(monkeypatch, "ligacoes_do_papel")
    with db.connect(read_only=True) as con:
        assert s._papel_a_conferir(con) == []
    assert finas == []
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert len(chamadas) == 1
    # outra ligação, de outro símbolo e sem linha, põe o dia de volta no
    # SQL: aí é a regra fina que não pode contar a removida como "rodando"
    from core import codigo, plano, variantes
    from core import portfolio as PF
    from tests._cadeia import campos_plano, mineracao, wfa
    v2 = variantes.criar("outro-simbolo", "rompimento_canal")
    mineracao(2, variante_id=v2)
    wfa(2, 2)
    plano.salvar(**campos_plano(wfa_id=2, run_id=2, symbol="WDO$N",
                                codigo_hash=codigo.hash_estrategia("rompimento_canal")),
                 agora=datetime(2026, 9, 1, 10))
    PF.adicionar_variante(PF.criar("pf2"), v2)
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET adicionado_em = '2026-09-01 09:00'")
    with db.connect(read_only=True) as con:
        assert s._papel_a_conferir(con) == []
    assert finas                              # passou pela regra fina


# ------------------------------------------------- reconferência na manhã
def _pregao_com_leilao(base, mono):
    """01/10 como aconteceu: a captura gravou o leilão de fechamento como
    candle próprio às 18:31, e a conferência das 18:45 bateu com o MT5."""
    dia = _minutos(datetime(2026, 10, 1, 9, 0), 3) + [
        datetime(2026, 10, 1, 18, 24), datetime(2026, 10, 1, 18, 31)]
    mt5 = MT5Falso(dia, tick=datetime(2026, 10, 1, 18, 45))
    s = _servico(mt5, datetime(2026, 10, 1, 18, 45), base / "ao_vivo", mono)
    s.volta()
    return s, mt5


def _de(dia):
    with db.connect(read_only=True) as con:
        return [r[0] for r in con.execute(
            "SELECT ts FROM bars_m1 WHERE CAST(ts AS DATE) = ? ORDER BY ts",
            [dia]).fetchall()]


def test_na_manha_seguinte_reconfere_ontem_uma_vez_e_exporta(base, monkeypatch):
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    assert datetime(2026, 10, 1, 18, 31) in _de(ontem)

    # de madrugada a corretora consolidou: o 18:31 sumiu do MT5
    mt5.minutos = [t for t in mt5.minutos if t.minute != 31]
    chamadas = []
    real = C.reconferir_dia
    monkeypatch.setattr(C, "reconferir_dia",
                        lambda *a, **k: chamadas.append(a[2]) or real(*a, **k))
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()

    assert chamadas == [ontem]
    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)
    no_parquet = [str(t)[:16] for t in db.read_bars_parquet("WIN$N")["ts"]]
    assert "2026-10-01T18:24" in no_parquet and "2026-10-01T18:31" not in no_parquet
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT last_ts FROM trading_days WHERE date = ?",
                           [ontem]).fetchone()[0] == datetime(2026, 10, 1, 18, 24)
    # a conferência de HOJE continua pendente: a de ontem não é a de hoje
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["conferencia"]["status"] == "pendente"

    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert chamadas == [ontem]               # uma vez só


def test_reconferencia_sem_o_dia_no_mt5_nao_apaga_e_tenta_de_novo(base):
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    antes = _de(ontem)
    mt5.minutos = []                         # terminal sem o histórico de ontem
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert _de(ontem) == antes
    with db.connect(read_only=True) as con:
        assert C.dias_a_reconferir(con, "WIN$N", datetime(2026, 10, 2).date()) == [ontem]
    mt5.minutos = [t for t in antes if t.minute != 31]
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)


def test_papel_do_dia_reconferido_fica_conferido_nos_candles_finais(base, ligacao):
    from core import papel
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"

    mt5.minutos = [t for t in mt5.minutos if t.minute != 31]
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()

    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)
    # a consolidação da corretora não é correção posterior: o papel foi
    # refeito nos candles finais, sem divergência
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"
    with db.connect(read_only=True) as con:
        assert papel.divergencias(con) == []
        gravado = con.execute("SELECT checksum FROM papel_pregoes WHERE dia = ?",
                              [ontem]).fetchone()[0]
        assert gravado == papel.checksum(con, "WIN$N", ontem)
    assert C.ler_estado(base / "ao_vivo" / "estado.json")["papel"]["divergencias"] == 0


@pytest.mark.parametrize("caso", ["removida_apos_o_fechamento", "codigo_mudou",
                                  "motor_mudou"])
def test_reconferencia_nao_reabre_o_que_o_conferir_refaria_diferente(
        base, ligacao, monkeypatch, caso):
    # refazer estes pregões os encerraria como "removida" ou "interrompido":
    # ficam como estavam, e a divergência acusa
    from core import codigo, papel
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    if caso == "removida_apos_o_fechamento":
        with db.connect_write() as con:
            con.execute("UPDATE portfolio_membros SET removido_em = '2026-10-01 19:00'")
    elif caso == "codigo_mudou":
        monkeypatch.setattr(codigo, "hash_estrategia", lambda nome: "outro")
    else:
        # o motor mudou de versão: refazer daria outro papel por outro motivo
        with db.connect_write() as con:
            con.execute("UPDATE papel_pregoes SET motor_versao = 'antigo'")
    mt5.minutos = [t for t in mt5.minutos if t.minute != 31]
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)
    assert _pregao_papel(ligacao, ontem) == ("conferido", None)
    with db.connect(read_only=True) as con:
        assert [d["dia"] for d in papel.divergencias(con)] == [ontem]


def _ontem_consolidado(s, mt5, mono, quando):
    mt5.minutos = [t for t in mt5.minutos if t.minute != 31]
    s.agora = lambda: quando
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()


def test_logo_depois_da_meia_noite_nao_reconfere(base):
    # a corretora ainda não consolidou: reconferir agora gravaria a marca e
    # a releitura que importa nunca aconteceria
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    _ontem_consolidado(s, mt5, mono, datetime(2026, 10, 2, 0, 10))
    assert datetime(2026, 10, 1, 18, 31) in _de(ontem)
    with db.connect(read_only=True) as con:
        assert C.dias_a_reconferir(con, "WIN$N", datetime(2026, 10, 2).date()) == [ontem]
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)


def test_falha_na_reconferencia_nao_impede_a_conferencia_de_hoje(base, monkeypatch):
    # 02/10 fechado e 01/10 por reconferir na mesma janela: um erro
    # qualquer (não só ValueError) na releitura de ontem não segura hoje
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    monkeypatch.setattr(C, "reconferir_dia", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("conexão caiu")))
    mt5.minutos = [t for t in mt5.minutos if t.minute != 31] + _minutos(
        datetime(2026, 10, 2, 9, 0), 3)
    mt5.tick = datetime(2026, 10, 2, 18, 45)
    s.agora = lambda: datetime(2026, 10, 2, 18, 45)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "concluida" and e["conferencia"]["dias"] == ["2026-10-02"]
    assert "conexão caiu" in e["reconferencia"]["erro"]
    assert e["erro"] is None


def test_reconferencia_que_falha_nao_marca_a_conferencia_de_hoje(base):
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    mt5.minutos = []                         # o MT5 não tem ontem
    s.agora = lambda: datetime(2026, 10, 2, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "pendente"
    assert "01/10/2026" in e["reconferencia"]["erro"]


def test_dia_que_o_mt5_deixou_de_servir_e_abandonado_depois_de_5_pregoes(base):
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    # cinco pregões depois, sem o MT5 ter devolvido 01/10 nenhuma vez
    with db.connect_write() as con:
        for d in (2, 5, 6, 7, 8):
            con.execute("INSERT INTO bars_m1 SELECT symbol, ts + INTERVAL (?) DAY, open, "
                        "high, low, close, tick_volume, volume, spread, src_ingest_id "
                        "FROM bars_m1 WHERE ts = '2026-10-01 09:00'", [d - 1])
    mt5.minutos = []
    pedidos = []
    real = s._barras_do_dia
    s._barras_do_dia = lambda dia, agora: pedidos.append(dia) or real(dia, agora)
    s.agora = lambda: datetime(2026, 10, 9, 8, 56)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert datetime(2026, 10, 1).date() not in pedidos
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["reconferencia"]["abandonados"] == ["2026-10-01"]


def _uma_operacao(monkeypatch):
    """O motor de verdade não opera em 5 candles iguais: uma operação fixa
    para provar que a reabertura não troca o op_id."""
    from core import papel
    op = {"entry_ts": datetime(2026, 10, 1, 9, 1), "exit_ts": datetime(2026, 10, 1, 9, 2),
          "side": 1, "contratos": 1, "entry_px": 100000, "exit_px": 100010,
          "points": 10, "bruto": 2.0, "custo": 1.0, "liquido": 1.0, "reason": 1,
          "mae": 0, "mfe": 10, "stop_px": None, "alvo_px": None, "aberta": False}
    monkeypatch.setattr(papel, "calcular", lambda *a, **k: [dict(op)])


def test_reabertura_do_papel_mantem_o_op_id(base, ligacao, monkeypatch):
    _uma_operacao(monkeypatch)
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    with db.connect(read_only=True) as con:
        antes = con.execute("SELECT op_id FROM papel_operacoes WHERE dia = ?", [ontem]).fetchall()
    assert len(antes) == 1
    _ontem_consolidado(s, mt5, mono, datetime(2026, 10, 2, 8, 56))
    assert datetime(2026, 10, 1, 18, 31) not in _de(ontem)
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT op_id FROM papel_operacoes WHERE dia = ?",
                           [ontem]).fetchall() == antes
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"


def test_papel_reaberto_depois_de_uma_queda_entre_candles_e_papel(base, ligacao, monkeypatch):
    # a reconferência dos candles fez COMMIT e o papel não foi reaberto
    # (processo fechado, falha): a janela seguinte o acha pela divergência
    from core import papel
    real = papel.reabrir_reconferido
    vezes = []

    def falha_uma_vez(*a, **k):
        vezes.append(1)
        if len(vezes) == 1:
            raise RuntimeError("caiu")
        return real(*a, **k)
    monkeypatch.setattr(papel, "reabrir_reconferido", falha_uma_vez)
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    _ontem_consolidado(s, mt5, mono, datetime(2026, 10, 2, 8, 56))
    with db.connect(read_only=True) as con:
        assert [d["dia"] for d in papel.divergencias(con)] == [ontem]
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    with db.connect(read_only=True) as con:
        assert papel.divergencias(con) == []
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"


def test_parquet_que_falha_na_reconferencia_nao_marca_a_conferencia_de_hoje(
        base, monkeypatch):
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    _export_falha_uma_vez(monkeypatch)
    _ontem_consolidado(s, mt5, mono, datetime(2026, 10, 2, 8, 56))
    e = C.ler_estado(base / "ao_vivo" / "estado.json")
    assert e["conferencia"]["status"] == "pendente"
    assert "Parquet" in e["reconferencia"]["erro"]
    mono.t += P.A_CADA_CONFERENCIA             # o Parquet é refeito na seguinte
    s.volta()
    no_parquet = [str(t)[:16] for t in db.read_bars_parquet("WIN$N")["ts"]]
    assert "2026-10-01T18:31" not in no_parquet


def test_correcao_posterior_a_reconferencia_nao_reabre_o_papel(base, ligacao, monkeypatch):
    # decisão 6 continua valendo: depois da reconferência, um candle mudado
    # por outra fonte (Sincronizar, reimportação) só acusa divergência
    from core import papel
    mono = Mono()
    s, mt5 = _pregao_com_leilao(base, mono)
    ontem = datetime(2026, 10, 1).date()
    _ontem_consolidado(s, mt5, mono, datetime(2026, 10, 2, 8, 56))
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"
    with db.connect_write() as con:
        from core.mt5_source import barras_de_taxas
        b = barras_de_taxas(mt5.copy_rates_range("WIN$N", 1, datetime(2026, 10, 1, 9),
                                                 datetime(2026, 10, 1, 9)))
        ing.ingest_df(con, b.with_columns(close=b["close"] + 5), "WIN$N", "manual.csv", "x",
                      source_max_ts=datetime(2026, 10, 2, 10, 0))
    chamadas = _contar(monkeypatch, "conferir")
    s.agora = lambda: datetime(2026, 10, 2, 10, 30)
    mono.t += P.A_CADA_CONFERENCIA
    s.volta()
    assert chamadas == []
    assert _pregao_papel(ligacao, ontem)[0] == "conferido"
    with db.connect(read_only=True) as con:
        assert [d["dia"] for d in papel.divergencias(con)] == [ontem]
