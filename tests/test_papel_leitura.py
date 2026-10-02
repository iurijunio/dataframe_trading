# tests/test_papel_leitura.py
"""Leituras da sub-tela Ao vivo › Operação (spec papel §6).

O cenário é semeado à mão — sem rodar o motor — para que cada número da
tela tenha uma conta feita aqui, no comentário ao lado do `assert`.

Portfólio "Teste" (ligado, conta demo sem limite, capital 10.000), dia
02/10/2026:
  - ligação 101, "alfa" (2 contratos, plano 12 desde 28/09, só 3_meses na
    expectativa, gravado mesmo assim). Um plano ANTERIOR (11) deixou +500
    em 25/09 — fora do acumulado. Hoje: A fechada (-30) e B ABERTA
    (compra 2 @ 130000, provisória +16).
  - ligação 102, "beta" (1 contrato, plano 13 sem expectativa). Hoje: C
    (+50) e D (-20).
  - ligação 103, "gama" (1 contrato, plano 14), desligada no meio do dia.
    Hoje: E (+40) e F (+300, entrada depois de desligar: conta = false).
  - ligação 104 removida em setembro: não aparece.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import papel as _papel  # noqa: E402
from core import papel_leitura as L  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401

DIA = date(2026, 10, 2)
# fração do pregão de hoje já andada: último candle 10:08 -> até 10:09,
# 69 min dos 510 entre 09:00 e o fechamento padrão do perfil (17:30)
F_HOJE = 69 / 510


def _ts(dia: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{dia} {hhmm}:00")


def _plano(con, pid, vid, wfa_id, vale, contratos, expectativa, estado="ativo",
           aposentado=None, mesmo_assim=False, pendencias=None):
    con.execute(
        "INSERT INTO planos_operacao (plano_id, wfa_id, symbol, strategy, "
        "variante_id, estado, vale_a_partir, aposentado_em, contratos, "
        "expectativa, gravado_mesmo_assim, pendencias, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [pid, wfa_id, "WIN$N", "rompimento_canal", vid, estado, vale,
         aposentado, contratos, json.dumps(expectativa), mesmo_assim,
         json.dumps(pendencias or []), "2026-09-01"])


def _pregao(con, lig, dia, plano_id, status, motivo=None,
            checksum="0:0:0:0:0"):
    con.execute(
        "INSERT INTO papel_pregoes (ligacao_id, dia, plano_id, status, motivo, "
        "checksum) VALUES (?,?,?,?,?,?)",
        [lig, dia, plano_id, status, motivo,
         checksum if status == "conferido" else None])


def _op(con, lig, plano_id, dia, entrada, saida, side, contratos, liquido,
        points, conta=True, aberta=False, entry_px=130000, exit_px=None,
        stop=None, alvo=None, calculado="23:00", reason=None):
    con.execute(
        "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
        "entry_ts, exit_ts, side, contratos, entry_px, exit_px, points, "
        "bruto, custo, liquido, reason, stop_px, alvo_px, aberta, conta, "
        "calculado_em) VALUES (nextval('seq_papel_op'), "
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [lig, plano_id, dia, _ts(dia, entrada),
         None if saida is None else _ts(dia, saida), side, contratos,
         entry_px, None if aberta else (exit_px or entry_px + points * side),
         points, liquido, 0.0, liquido,
         None if aberta else (reason if reason is not None else 3),
         stop, alvo, aberta, conta, _ts(dia, calculado)])


# fechamento das barras do dia: o que marca a operação aberta B
BARRAS = [("09:00", 130000), ("09:15", 130000), ("09:30", 130000),
          ("09:40", 130000), ("09:50", 130000), ("10:05", 130000),
          ("10:06", 129900), ("10:07", 129950), ("10:08", 130050)]


@pytest.fixture
def cenario(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO contas (conta_id, nome, tipo, "
                    "limite_perda_dia, criado_em) VALUES "
                    "(10, 'demo-1', 'demo', NULL, '2026-09-01')")
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em, "
                    "capital, ligado, conta_demo_id, conta_real_id) VALUES "
                    "(1, 'Teste', '2026-09-01', 10000, true, 10, NULL), "
                    "(2, 'Outro', '2026-09-01', NULL, false, NULL, NULL)")
        for vid, nome in ((1, "alfa"), (2, "beta"), (3, "gama")):
            con.execute("INSERT INTO estrategia_variantes (variante_id, "
                        "estrategia, nome, criado_em) VALUES (?,?,?,?)",
                        [vid, "rompimento_canal", nome, "2026-09-01"])
        for lig, vid, ligada, removido in ((101, 1, True, None),
                                           (102, 2, True, None),
                                           (103, 3, False, None),
                                           (104, 1, True, "2026-09-15")):
            con.execute(
                "INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
                "variante_id, adicionado_em, removido_em, fase, fase_desde, "
                "ligada) VALUES (?,1,?,?,?,'papel',?,?)",
                [lig, vid, "2026-09-01", removido, "2026-09-01", ligada])

        _plano(con, 11, 1, 1, "2026-09-01", 2, {}, estado="aposentado",
               aposentado="2026-09-28")
        _plano(con, 12, 1, 2, "2026-09-28", 2,
               {"3_meses": {"pregoes": 63, "p10": -630.0, "p50": 630.0,
                            "p90": 1890.0}},
               mesmo_assim=True,
               pendencias=[{"nome": "SPA", "motivo": "reprovado"}])
        _plano(con, 13, 2, 3, "2026-09-29", 1, {})
        _plano(con, 14, 3, 4, "2026-09-29", 1,
               {"3_meses": {"pregoes": 63, "p10": -63.0, "p50": 126.0,
                            "p90": 315.0}})

        # ---- pregões
        _pregao(con, 101, "2026-09-25", 11, "conferido")
        for d in ("2026-09-29", "2026-09-30", "2026-10-01"):
            _pregao(con, 101, d, 12, "conferido")
        _pregao(con, 101, "2026-10-02", 12, "rodando")
        for d in ("2026-09-30", "2026-10-01"):
            _pregao(con, 102, d, 13, "conferido")
        _pregao(con, 102, "2026-10-02", 13, "rodando")
        # gama: desligada o pregão de 30/09 inteiro (régua não anda),
        # religada em 01/10 e desligada de novo hoje às 09:30
        for eid, quando, tipo in ((1, "2026-09-30 08:00", "membro_desligado"),
                                  (2, "2026-10-01 08:00", "membro_ligado"),
                                  (3, "2026-10-02 09:30", "membro_desligado")):
            con.execute("INSERT INTO ao_vivo_eventos (evento_id, quando, tipo, "
                        "origem, portfolio_id, ligacao_id) "
                        "VALUES (?,?,?,'usuario',1,103)", [eid, quando, tipo])
        _pregao(con, 103, "2026-09-30", 14, "conferido")
        _pregao(con, 103, "2026-10-01", 14, "conferido")
        _pregao(con, 103, "2026-10-02", 14, "rodando")

        # ---- operações de dias anteriores
        _op(con, 101, 11, "2026-09-25", "10:00", "10:30", 1, 2, 500.0, 1250)
        _op(con, 101, 12, "2026-09-29", "10:00", "10:30", 1, 2, 100.0, 250)
        _op(con, 101, 12, "2026-09-30", "10:00", "10:30", -1, 2, -40.0, -100)
        _op(con, 101, 12, "2026-10-01", "10:00", "10:30", 1, 2, 60.0, 150)
        _op(con, 102, 13, "2026-09-30", "11:00", "11:20", 1, 1, 20.0, 100)
        _op(con, 102, 13, "2026-10-01", "11:00", "11:20", -1, 1, -10.0, -50)
        _op(con, 103, 14, "2026-10-01", "12:00", "12:20", 1, 1, 15.0, 75)

        # ---- hoje
        d = "2026-10-02"
        _op(con, 103, 14, d, "09:05", "09:15", 1, 1, 40.0, 200)          # E
        _op(con, 101, 12, d, "09:10", "09:30", -1, 2, -30.0, -75)        # A
        _op(con, 102, 13, d, "09:20", "09:40", 1, 1, 50.0, 250)          # C
        _op(con, 102, 13, d, "09:45", "09:50", -1, 1, -20.0, -100)       # D
        _op(con, 103, 14, d, "10:00", "10:20", 1, 1, 300.0, 1500,
            conta=False)                                                  # F
        _op(con, 101, 12, d, "10:05", None, 1, 2, 16.0, 45, aberta=True,
            stop=129900, alvo=130300, calculado="10:09")                 # B

        for hhmm, close in BARRAS:
            con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, "
                        "close, src_ingest_id) VALUES ('WIN$N',?,?,?,?,?,1)",
                        [_ts(d, hhmm), close, close, close, close])

        # o WFA de cada plano (o 1 é do plano antigo: fora do comparativo)
        for wfa_id, n, liq, ctr, pts in ((1, 1, 999.0, 2, 9999),
                                         (2, 1, 100.0, 2, 260),
                                         (2, 2, -50.0, 2, -120),
                                         (3, 1, 30.0, 1, 160),
                                         (4, 1, -10.0, 1, -40)):
            con.execute("INSERT INTO wfa_trades (wfa_id, n, liquido, "
                        "contratos, points) VALUES (?,?,?,?,?)",
                        [wfa_id, n, liq, ctr, pts])
    return banco


def _ler():
    return db.connect(read_only=True)


# ------------------------------------------------------------------ seletor
def test_portfolios_com_papel(cenario):
    with _ler() as con:
        out = L.portfolios_com_papel(con)
    assert [(p["portfolio_id"], p["nome"], p["ligado"]) for p in out] == [
        (2, "Outro", False), (1, "Teste", True)]


# ------------------------------------------------------------------- resumo
def test_resumo_numeros_do_dia(cenario):
    with _ler() as con:
        r = L.resumo(con, 1, DIA, hoje=DIA)
    # fechadas que contam: E +40, A -30, C +50, D -20 = 40; + B aberta +16.
    # F (+300) é de depois de desligar a gama: fora.
    assert r["resultado_hoje"] == pytest.approx(56.0)
    # só B aberta: compra de 2
    assert r["posicao"] == {"liquida": 2,
                            "por_ligacao": {101: 2, 102: 0, 103: 0}}
    # curva por barra: 09:15 +40 (E) · 09:30 +10 (A) · 09:40 +60 (C) ·
    # 09:50 +40 (D) · 10:05 40 + B(16 + (130000-130050)·0,2·2 = -4) = 36 ·
    # 10:06 40 + (16 - 150·0,4 = -44) = -4 · 10:07 16 · 10:08 56
    assert r["pior_momento"]["valor"] == pytest.approx(-4.0)
    assert r["pior_momento"]["quando"] == _ts("2026-10-02", "10:06")
    assert r["limite_dia"] is None
    # desde o plano em vigor de cada ligação (nunca o +500 do plano 11):
    # alfa 100-40+60-30+16 = 106 · beta 20-10+50-20 = 40 · gama 15+40 = 55
    assert r["acumulado"]["valor"] == pytest.approx(201.0)
    assert r["acumulado"]["operacoes"] == 11            # 5 + 4 + 2
    assert r["acumulado"]["pregoes"] == 4               # 29/09 a 02/10
    assert r["n_variantes"] == 3
    assert r["n_operando"] == 2                         # gama desligada
    assert r["contas"]["demo"] == {"conta_id": 10, "nome": "demo-1",
                                   "limite_perda_dia": None}
    assert r["contas"]["real"] is None
    assert r["capital"] == 10000.0


def test_resumo_limite_da_conta_demo(cenario):
    with db.connect_write() as con:
        con.execute("UPDATE contas SET limite_perda_dia = 500 "
                    "WHERE conta_id = 10")
    with _ler() as con:
        assert L.resumo(con, 1, DIA, hoje=DIA)["limite_dia"] == 500.0


def test_resumo_dia_passado_preso_em_rodando_nao_e_posicao_viva(cenario):
    # vendo 02/10 no dia seguinte: a conferência não rodou, B continua
    # "aberta" no banco — mas não é posição de agora
    with _ler() as con:
        r = L.resumo(con, 1, DIA, hoje=date(2026, 10, 3))
    assert r["posicao"]["liquida"] == 0
    assert r["n_operando"] == 0                 # nenhum pregão vivo
    assert r["resultado_hoje"] == pytest.approx(56.0)   # último número que há


def test_pior_momento_nao_depende_do_relogio_do_pc(cenario):
    # o relógio do PC 70 s atrás da corretora: o cálculo das 10:09 sai
    # carimbado 10:07:50. A marcação é a mesma — o pior momento também.
    with db.connect_write() as con:
        con.execute("UPDATE papel_operacoes SET calculado_em = "
                    "'2026-10-02 10:07:50' WHERE aberta")
    with _ler() as con:
        r = L.resumo(con, 1, DIA, hoje=DIA)
    assert r["pior_momento"]["valor"] == pytest.approx(-4.0)
    assert r["pior_momento"]["quando"] == _ts("2026-10-02", "10:06")


def test_pior_momento_com_papel_pendente_e_barra_nova(cenario):
    # candle das 10:09 gravado, papel ainda não recalculado: no mesmo preço
    # da marcação nada muda...
    with db.connect_write() as con:
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', '2026-10-02 10:09:00', "
                    "130050, 130050, 130050, 130050, 1)")
    with _ler() as con:
        assert L.resumo(con, 1, DIA, hoje=DIA)["pior_momento"]["valor"] \
            == pytest.approx(-4.0)
    # ...e num preço pior é preço real: 40 + 16 + (129800-130050)·0,2·2 = -44
    with db.connect_write() as con:
        con.execute("UPDATE bars_m1 SET close = 129800 "
                    "WHERE ts = '2026-10-02 10:09:00'")
    with _ler() as con:
        r = L.resumo(con, 1, DIA, hoje=DIA)
    assert r["pior_momento"]["valor"] == pytest.approx(-44.0)
    assert r["pior_momento"]["quando"] == _ts("2026-10-02", "10:09")


# ---------------------------------------------------------------- variantes
def test_variantes_numeros_e_ordem(cenario):
    with _ler() as con:
        vs = L.variantes(con, 1, DIA, hoje=DIA)
    # posição aberta primeiro (alfa), depois resultado do dia: gama 40 > beta 30
    assert [v["ligacao_id"] for v in vs] == [101, 103, 102]
    alfa, gama, beta = vs
    assert alfa["nome"] == "alfa" and alfa["fase"] == "papel"
    assert alfa["posicao"] == 2
    assert alfa["hoje"] == pytest.approx(-14.0)        # -30 + 16
    assert alfa["n_ops"] == 2 and alfa["acerto"] == "0/1"
    assert alfa["acumulado"] == pytest.approx(106.0)
    assert alfa["contratos"] == 2 and alfa["plano_id"] == 12
    assert alfa["gravado_mesmo_assim"] is True
    assert alfa["pendencias"] == [{"nome": "SPA", "motivo": "reprovado"}]
    assert alfa["status"] == "rodando" and alfa["ligada"] is True
    assert beta["hoje"] == pytest.approx(30.0) and beta["acerto"] == "1/2"
    assert beta["acumulado"] == pytest.approx(40.0)
    assert beta["gravado_mesmo_assim"] is False
    # F não conta: só E
    assert gama["hoje"] == pytest.approx(40.0)
    assert gama["n_ops"] == 1 and gama["acerto"] == "1/1"
    assert gama["acumulado"] == pytest.approx(55.0)
    assert gama["ligada"] is False
    # cor pelo ligacao_id entre TODAS as ligações (a removida também):
    # remover uma não troca a cor das outras
    assert (alfa["cor"], beta["cor"], gama["cor"]) == (0, 1, 2)


def test_variantes_pregao_preso_vira_nao_conferido(cenario):
    with _ler() as con:
        vs = {v["ligacao_id"]: v for v in
              L.variantes(con, 1, DIA, hoje=date(2026, 10, 3))}
    assert vs[101]["status"] == "nao_conferido"
    assert vs[101]["posicao"] == 0
    assert vs[101]["motivo"]


def test_variantes_status_pulado_com_motivo(cenario):
    with db.connect_write() as con:
        con.execute("UPDATE papel_pregoes SET status = 'pulado', "
                    "motivo = 'código mudou desde o plano' "
                    "WHERE ligacao_id = 102 AND dia = '2026-10-02'")
    with _ler() as con:
        vs = {v["ligacao_id"]: v for v in L.variantes(con, 1, DIA, hoje=DIA)}
        r = L.resumo(con, 1, DIA, hoje=DIA)
    assert vs[102]["status"] == "pulado"
    assert vs[102]["motivo"] == "código mudou desde o plano"
    assert r["n_operando"] == 1


# --------------------------------------------------------------- operações
def test_operacoes_do_dia(cenario):
    with _ler() as con:
        ops = L.operacoes_do_dia(con, 1, DIA, hoje=DIA)
        so_gama = L.operacoes_do_dia(con, 1, DIA, ligacao_id=103, hoje=DIA)
    assert [(o["entry_ts"].strftime("%H:%M"), o["ligacao_id"]) for o in ops] \
        == [("09:05", 103), ("09:10", 101), ("09:20", 102), ("09:45", 102),
            ("10:00", 103), ("10:05", 101)]
    b = ops[-1]
    assert b["situacao"] == "aberta"
    assert b["aberta"] is True and b["exit_ts"] is None
    assert b["provisorio"] is True and b["liquido"] == pytest.approx(16.0)
    assert (b["stop_px"], b["alvo_px"]) == (129900, 130300)
    assert b["variante"] == "alfa"
    assert [o["conta"] for o in so_gama] == [True, False]


# --------------------------------------------------------------- marcadores
def test_marcadores(cenario):
    with _ler() as con:
        m = L.marcadores(con, 1, DIA, hoje=DIA)
    mk = m["marcadores"]
    # 6 entradas + 5 saídas (B ainda aberta)
    assert len(mk) == 11
    assert [x["time"] for x in mk] == sorted(x["time"] for x in mk)
    # horário de parede como se fosse UTC (convenção de `ui.data.to_epoch`)
    epoch_b = int((_ts("2026-10-02", "10:05")
                   - datetime(1970, 1, 1)).total_seconds())
    b = [x for x in mk if x["time"] == epoch_b]
    # sem `color`: a tela pinta pelo índice da variante
    assert b == [{"time": epoch_b, "position": "belowBar", "shape": "arrowUp",
                  "text": "C", "cor": 0, "conta": True, "ligacao_id": 101}]
    epoch_f = int((_ts("2026-10-02", "10:00")
                   - datetime(1970, 1, 1)).total_seconds())
    f = [x for x in mk if x["time"] == epoch_f]
    assert f[0]["conta"] is False and f[0]["cor"] == 2     # F não conta
    assert {(x["tipo"], x["price"]) for x in m["linhas_abertas"]} == {
        ("stop", 129900), ("alvo", 130300)}


def test_dia_passado_preso_nao_tem_aberta_nem_linhas(cenario):
    hoje = date(2026, 10, 3)
    with _ler() as con:
        ops = L.operacoes_do_dia(con, 1, DIA, hoje=hoje)
        m = L.marcadores(con, 1, DIA, hoje=hoje)
    b = ops[-1]
    assert b["situacao"] == "nao_conferido"
    assert b["aberta"] is False and b["provisorio"] is False
    assert all(o["situacao"] == "fechada" for o in ops[:-1])
    assert m["linhas_abertas"] == []
    assert len(m["marcadores"]) == 11       # a entrada de B continua lá


# ------------------------------------------------------- papel × esperado
def test_interpolacao_da_expectativa():
    exp = {"3_meses": {"pregoes": 63, "p10": 0, "p50": 630.0, "p90": 0},
           "6_meses": {"pregoes": 126, "p10": 0, "p50": 1890.0, "p90": 0}}
    assert L._interp(exp, "p50", 0) == 0.0
    assert L._interp(exp, "p50", 63) == pytest.approx(630.0)
    # 630 + 37/63 · 1260 = 1370
    assert L._interp(exp, "p50", 100) == pytest.approx(1370.0)
    # depois do último marco segue a inclinação do último trecho (20/pregão)
    assert L._interp(exp, "p50", 200) == pytest.approx(3370.0)
    assert L._interp({}, "p50", 10) is None


def test_faixa_cresce_com_raiz_de_n():
    exp = {"3_meses": {"pregoes": 63, "p10": 0.0, "p50": 630.0, "p90": 1260.0},
           "6_meses": {"pregoes": 126, "p10": 630.0, "p50": 1890.0,
                       "p90": 3150.0}}
    # n = 16: marco mais perto é 63 (distância de 1/2 da faixa: -630, +630)
    assert L._interp(exp, "p10", 16) == pytest.approx(
        160 - 630 * math.sqrt(16 / 63))
    assert L._interp(exp, "p90", 16) == pytest.approx(
        160 + 630 * math.sqrt(16 / 63))
    # no marco, o próprio valor gravado
    assert L._interp(exp, "p10", 63) == pytest.approx(0.0)
    # n = 100: mais perto de 126 (26) que de 63 (37); faixa -1260
    assert L._interp(exp, "p10", 100) == pytest.approx(
        1370 - 1260 * math.sqrt(100 / 126))
    # depois do último marco: mediana estendida (3370), N = 126
    assert L._interp(exp, "p10", 200) == pytest.approx(
        3370 - 1260 * math.sqrt(200 / 126))
    assert L._interp(exp, "p10", 0) == pytest.approx(0.0)


@pytest.mark.parametrize("v,faixa", [(-50, "abaixo_p10"), (0, "p10_p50"),
                                     (50, "p50_p90"), (150, "acima_p90")])
def test_faixa(v, faixa):
    assert L._faixa(v, -10, 10, 100) == faixa


def test_curva_por_variante(cenario):
    with _ler() as con:
        c = L.curva_vs_esperado(con, 1, 101, hoje=DIA)
    assert c["dias"] == [date(2026, 9, 29), date(2026, 9, 30),
                         date(2026, 10, 1), date(2026, 10, 2)]
    # 100, -40, +60, -14 (hoje: A -30 + B +16)
    assert c["papel"] == pytest.approx([100, 60, 120, 106])
    # régua: 3 pregões cheios + hoje pela fração andada — último candle
    # 10:08, então até 10:09 = 69 min de 09:00→17:30 (510 min)
    n = [1, 2, 3, 3 + F_HOJE]
    # mediana 630/63 = 10 por pregão; faixa ±1260 no marco, com √(n/63)
    assert c["mediana"] == pytest.approx([10 * x for x in n])
    assert c["p10"] == pytest.approx(
        [10 * x - 1260 * math.sqrt(x / 63) for x in n])
    assert c["p90"] == pytest.approx(
        [10 * x + 1260 * math.sqrt(x / 63) for x in n])
    # 31,4 <= 106 <= 31,4 + 281,1
    assert c["faixa_atual"] == "p50_p90"
    assert c["aviso"] is None


def test_curva_por_variante_sem_expectativa(cenario):
    with _ler() as con:
        c = L.curva_vs_esperado(con, 1, 102, hoje=DIA)
    assert c["papel"] == pytest.approx([20, 10, 40])
    assert c["mediana"] is None and c["p10"] is None and c["p90"] is None
    assert c["faixa_atual"] is None
    assert c["aviso"]


def test_curva_da_gama_acima_de_p90(cenario):
    with _ler() as con:
        c = L.curva_vs_esperado(con, 1, 103, hoje=DIA)
    # 30/09 desligada o dia todo: 0; 01/10 15; hoje +40 (F fora)
    assert c["papel"] == pytest.approx([0, 15, 55])
    # a régua não anda em 30/09; hoje anda a fração (ligada 09:00→09:30)
    n = [0, 1, 1 + F_HOJE]
    assert c["mediana"] == pytest.approx([2 * x for x in n])
    # p90: 2(1+f) + 189·√((1+f)/63) ≈ 27,6 < 55
    assert c["p90"][-1] == pytest.approx(
        2 * n[-1] + 189 * math.sqrt(n[-1] / 63))
    assert c["faixa_atual"] == "acima_p90"


def test_regua_nao_anda_com_a_variante_desligada_o_dia_todo(cenario):
    # gama desligada desde ontem cedo: hoje não anda, nem pela fração
    with db.connect_write() as con:
        con.execute("DELETE FROM ao_vivo_eventos WHERE evento_id = 3")
        con.execute("INSERT INTO ao_vivo_eventos (evento_id, quando, tipo, "
                    "origem, portfolio_id, ligacao_id) VALUES (4, "
                    "'2026-10-01 18:00', 'membro_desligado', 'usuario', 1, 103)")
    with _ler() as con:
        c = L.curva_vs_esperado(con, 1, 103, hoje=DIA)
    assert c["mediana"] == pytest.approx([0, 2, 2])


def test_curva_do_portfolio_soma_medianas_sem_faixa(cenario):
    with _ler() as con:
        c = L.curva_vs_esperado(con, 1, hoje=DIA)
    assert c["dias"] == [date(2026, 9, 29), date(2026, 9, 30),
                         date(2026, 10, 1), date(2026, 10, 2)]
    # 100 · +(-40+20) · +(60-10+15) · +(-14+30+40)
    assert c["papel"] == pytest.approx([100, 80, 145, 201])
    # alfa 10/pregão (n = 1, 2, 3, 3+f) + gama 2/pregão (n = 0, 0, 1, 1+f);
    # beta sem expectativa fica fora
    hoje = 10 * (3 + F_HOJE) + 2 * (1 + F_HOJE)
    assert c["mediana"] == pytest.approx([10, 20, 32, hoje])
    assert c["p10"] is None and c["p90"] is None
    assert c["faixa_atual"] is None
    assert c["diferenca_mediana"] == pytest.approx(201 - hoje)
    assert "1 variante" in c["aviso"]


# --------------------------------------------------------------- comparativo
def test_comparativo(cenario):
    with _ler() as con:
        c = L.comparativo(con, 1, hoje=DIA)
    e = c["esperado_wfa"]
    # WFA 2, 3, 4 (o 1 é do plano antigo). Por contrato: 50, -25, 30, -10
    assert e["n"] == 4
    assert e["resultado_por_contrato"] == pytest.approx(45 / 4)
    assert e["pontos_por_operacao"] == pytest.approx((260 - 120 + 160 - 40) / 4)
    assert e["fator_lucro"] == pytest.approx(80 / 35)
    assert e["acerto"] == pytest.approx(0.5)
    assert e["contratos_por_operacao"] == pytest.approx(1.5)
    p = c["papel"]
    # fechadas que contam, desde o plano em vigor (B aberta, F e o +500 fora).
    # Por contrato: alfa 50,-20,30,-15 · beta 20,-10,50,-20 · gama 15,40
    assert p["n"] == 10
    assert p["resultado_por_contrato"] == pytest.approx(140 / 10)
    assert p["pontos_por_operacao"] == pytest.approx(700 / 10)
    assert p["fator_lucro"] == pytest.approx(205 / 65)
    assert p["acerto"] == pytest.approx(0.6)
    assert p["contratos_por_operacao"] == pytest.approx(1.4)
    assert p["total"] == pytest.approx(185.0)
    assert c["demo"] is None and c["real"] is None


def test_metricas_sem_perda_e_sem_operacao():
    m = L._metricas([(10.0, 1, 50)])
    assert m["fator_lucro"] == math.inf
    vazio = L._metricas([])
    assert vazio["n"] == 0 and vazio["fator_lucro"] is None


# ------------------------------------------------------------------ alertas
def test_alertas(cenario):
    with db.connect_write() as con:
        con.execute("UPDATE papel_pregoes SET status = 'interrompido', "
                    "motivo = 'código mudou no meio do pregão' "
                    "WHERE ligacao_id = 102 AND dia = '2026-10-02'")
        # pregão de ontem que a conferência não fechou
        con.execute("UPDATE papel_pregoes SET status = 'rodando', "
                    "checksum = NULL "
                    "WHERE ligacao_id = 103 AND dia = '2026-10-01'")
        # preso também, mas do plano ANTIGO da alfa: história encerrada
        con.execute("UPDATE papel_pregoes SET status = 'rodando' "
                    "WHERE ligacao_id = 101 AND dia = '2026-09-25'")
        # candles de 30/09 mudaram depois da conferência
        con.execute("UPDATE papel_pregoes SET checksum = 'x' "
                    "WHERE ligacao_id = 101 AND dia = '2026-09-30'")
    with _ler() as con:
        a = L.alertas(con, 1, DIA, hoje=DIA)
        so_beta = _papel.divergencias(con, ligacoes=[102])
        todas = _papel.divergencias(con)
    tipos = sorted((x["tipo"], x["ligacao_id"]) for x in a)
    assert tipos == sorted([("mesmo_assim", 101), ("interrompido", 102),
                            ("nao_conferido", 103), ("divergencia", 101)])
    assert all(x["texto"] for x in a)
    # o filtro por ligação; e a impressão agrupada bate com a de `checksum`
    assert so_beta == []
    assert [(d["ligacao_id"], d["dia"], d["atual"]) for d in todas] == [
        (101, date(2026, 9, 30), "0:0:0:0:0")]


def test_alertas_sem_nada_alem_do_mesmo_assim(cenario):
    with _ler() as con:
        a = L.alertas(con, 1, DIA, hoje=DIA)
    assert [(x["tipo"], x["ligacao_id"]) for x in a] == [("mesmo_assim", 101)]
