"""Ponte captura -> processo da conta real (spec conta-real §4.2, R8–R11):
ida e volta do arquivo, frescor, leitura tolerante, escrita atômica com
PermissionError (Windows) e o ack."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

from core import db_manager as db
from core import ponte
from core.papel_vivo import POSICAO, ZERADO, Desejado

ENTRADA = datetime(2026, 10, 9, 10, 1)
TOQUE = datetime(2026, 10, 9, 10, 9, 30)


def _desejados():
    return {
        7: Desejado(estado=POSICAO, lado=1, entry_ts=ENTRADA, entry_px=189_000,
                    stop_px=188_800, alvo_px=189_400, contratos=3,
                    motivo="rompimento"),
        9: Desejado(estado=ZERADO, lado=-1, motivo="stop", toque_em=TOQUE),
    }


CONTRATO = {"simbolo": "WINV26", "motivo": None, "vence_em": date(2026, 10, 14),
            "amanha": None}


def _dados(seq=3, agora=None):
    return ponte.serializar(_desejados(), True, CONTRATO, seq,
                            agora or datetime(2026, 10, 9, 10, 1, 5))


def test_pasta_da_ponte_e_desviada_pelo_conftest(tmp_path):
    assert ponte.PASTA != db.DATA / "ao_vivo"
    assert ponte.PASTA.is_relative_to(tmp_path)


def test_ida_e_volta_preserva_o_desejado_menos_contratos(tmp_path):
    assert ponte.escrever(_dados(seq=3))
    dados = ponte.ler_arquivo()
    des, disp, contrato, seq, vivo = ponte.ler(dados)
    assert set(des) == {7, 9}                       # ligacao_id volta a int
    assert des[7] == Desejado(estado=POSICAO, lado=1, entry_ts=ENTRADA,
                              entry_px=189_000, stop_px=188_800, alvo_px=189_400,
                              contratos=0, motivo="rompimento")
    assert des[9].toque_em == TOQUE and des[9].entry_ts is None
    assert disp is True and seq == 3 and isinstance(vivo, float)
    assert contrato == CONTRATO                     # datas voltam a date
    assert dados["versao"] == 1 and dados["escrito_em_srv"] == "2026-10-09T10:01:05"
    assert "contratos" not in dados["desejados"]["7"]


def test_fresco_olha_o_batimento_do_pc():
    dados = {"vivo_em": 100.0}
    assert ponte.fresco(dados, agora_pc=104.9)
    assert not ponte.fresco(dados, agora_pc=105.1)
    assert ponte.fresco(dados, agora_pc=105.1, limite_s=10)
    assert not ponte.fresco({})
    recente = _dados()
    assert ponte.fresco(recente)                    # agora (padrão)
    assert not ponte.fresco(recente, agora_pc=time.time() + 60)


def test_json_incompleto_ou_ausente_vira_none():
    assert ponte.ler_arquivo() is None              # arquivo ausente
    pasta = ponte.PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / ponte.ARQ_DESEJADOS
    arq.write_bytes(b'{"versao": 1, "seq"')         # JSON cortado
    assert ponte.ler_arquivo() is None
    arq.write_text(json.dumps({"versao": 1, "seq": 1}), encoding="utf-8")
    assert ponte.ler_arquivo() is None              # faltam campos
    arq.write_text("[1, 2]", encoding="utf-8")
    assert ponte.ler_arquivo() is None


def test_permission_error_duas_vezes_depois_sucesso(monkeypatch):
    real = os.replace
    chamadas = []

    def preso(src, dst):
        chamadas.append(src)
        if len(chamadas) <= 2:
            raise PermissionError("em uso")
        return real(src, dst)
    monkeypatch.setattr(ponte.os, "replace", preso)
    assert ponte.escrever(_dados(seq=4)) is True
    assert len(chamadas) == 3
    assert ponte.ler_arquivo()["seq"] == 4


def test_permission_error_sempre_devolve_false_sem_levantar(monkeypatch):
    chamadas = []

    def preso(src, dst):
        chamadas.append(src)
        raise PermissionError("em uso")
    monkeypatch.setattr(ponte.os, "replace", preso)
    assert ponte.escrever(_dados()) is False
    assert len(chamadas) == ponte.TENTATIVAS


def test_falha_de_escrita_qualquer_nao_levanta(monkeypatch):
    def quebra(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(ponte.os, "replace", quebra)
    assert ponte.escrever(_dados()) is False


def test_ack_ida_e_volta_e_ausencia():
    assert ponte.ler_ack() is None
    assert ponte.gravar_ack(12) is True
    assert ponte.ler_ack() == 12
    (ponte.PASTA / ponte.ARQ_ACK).write_text("{ruim", encoding="utf-8")
    assert ponte.ler_ack() is None


def test_real_ativo_so_com_batimento_recente():
    assert ponte.real_ativo() is False              # sem arquivo
    ponte.gravar_vivo_real()
    assert ponte.real_ativo() is True
    assert ponte.real_ativo(agora_pc=time.time() + 6) is False
    assert ponte.real_ativo(agora_pc=time.time() + 6, limite_s=10) is True
