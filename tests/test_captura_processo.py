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

    def initialize(self, path=None):
        self.inits += 1
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
    # o MT5 recusa o símbolo
    agora = datetime(2026, 10, 1, 10, 0)
    mt5 = MT5Falso([], tick=agora)
    mt5.symbol_select = lambda s, on: False
    s = _servico(mt5, agora, base / "ao_vivo")
    with pytest.raises(P.ErroDeConfiguracao, match="não tem WIN\\$N"):
        s.volta()


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
