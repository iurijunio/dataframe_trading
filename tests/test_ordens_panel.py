"""Ao vivo › Operação com a demo (parte 4, tarefa 15).

Os construtores de `ui/components/ordens_panel.py` recebem dicionários no
formato do `estado.json["ordens"]` (core.ordens.Motor.passo) e das leituras
de `core.papel_leitura`; nenhum teste lê o banco real nem o estado.json
real. As leituras novas (`operacoes_demo`, `comparativo_demo`) rodam num
banco descartável semeado à mão — cada número tem a conta no comentário.

WIN: 1 tick = 5 pontos, 1 ponto = R$ 0,20 por contrato.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import papel_leitura as PL  # noqa: E402
from tests._cadeia import banco  # noqa: E402,F401
from ui.components import ordens_panel as OR  # noqa: E402

AGORA = datetime(2026, 10, 14, 14, 37, 12)
TICK = 5


# ------------------------------------------------------------ utilidades
def textos(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (str, int, float)):
        return str(c)
    if isinstance(c, (list, tuple)):
        return " ".join(textos(x) for x in c)
    return textos(getattr(c, "children", None))


def todos(c):
    if c is None or isinstance(c, (str, int, float)):
        return []
    if isinstance(c, (list, tuple)):
        return [x for y in c for x in todos(y)]
    return [c] + todos(getattr(c, "children", None))


def classes(c) -> str:
    return getattr(c, "className", "") or ""


def _dicas(c) -> list[str]:
    return [x for x in todos(c) if "dica-mark" in classes(x)]


def _ordens(**mudar):
    """Uma volta com a demo enviando: ligação 7 comprada 2 (confere),
    ligação 8 vendida 1 com a saída pendente há 6 s na 3ª tentativa."""
    o = {
        "foto": "ok", "falhou": False, "n_demo": 2,
        "vivo_em": "2026-10-14T14:37:11", "ordens_em": "2026-10-14T14:30:02",
        "contrato": "WINV26", "contrato_dia": "WINV26",
        "conta": {"conta_id": 3, "login": 1193398927,
                  "servidor": "ClearInvestimentos-DEMO", "confere": True,
                  "hedging": True, "algo": True, "margem_livre": 8420.0},
        "envio": True, "zerar": False, "travada": None,
        "perda": {"este": 100.0, "outros": 40.0, "fora": 24.0, "total": 164.0,
                  "por_portfolio": {"1": 100.0, "2": 40.0}},
        "limite": 500.0,
        "ligacoes": {
            "7": {"desejado": "posicao", "papel": "posicao", "motivo": None,
                  "lado": 1, "entry_ts": "2026-10-14T14:21:00",
                  "stop_px": 188645, "alvo_px": 189665, "contratos": 2,
                  "tentativas": 1,
                  "posicoes": [{"ticket": 111, "simbolo": "WINV26", "lado": 1,
                                "volume": 2.0, "preco": 189010.0,
                                "sl": 188645.0, "tp": 189665.0,
                                # +47 ticks = 235 pts × 2 × 0,20
                                "resultado": 94.0, "saida_desde": None,
                                "tentativas": 0}]},
            "8": {"desejado": "zerado", "papel": "zerado", "motivo": "papel zerado",
                  "lado": 0, "entry_ts": None, "stop_px": None, "alvo_px": None,
                  "contratos": 0, "tentativas": 0,
                  "posicoes": [{"ticket": 222, "simbolo": "WINV26", "lado": -1,
                                "volume": 1.0, "preco": 188335.0,
                                "sl": 188635.0, "tp": 187735.0,
                                "resultado": -10.0,
                                "saida_desde": "2026-10-14T14:37:06",
                                "tentativas": 3}]},
        },
        "chamados": [],
        "comandos": [],
    }
    o.update(mudar)
    return o


NOMES = {7: "variante-canal-M7", 8: "variante-medias-abertura-M7"}


# --------------------------------------------------------- faixa de saúde
def test_saude_mostra_os_sete_itens_com_dica():
    f = OR.faixa_saude(_ordens(), ultimo_candle="2026-10-14T14:36:00",
                       atraso_ms=700, agora=AGORA)
    t = textos(f)
    for rot in ("MT5", "Algo Trading", "Conta logada", "Margem livre",
                "Sinal de vida", "Último candle", "Ordem (média)"):
        assert rot in t
    assert "conectado" in t and "ligado" in t and "1193398927" in t
    assert "R$ 8.420" in t and "há 1 s" in t and "14:36" in t and "0,7 s" in t
    assert len(_dicas(f)) == 7


def test_saude_atraso_medio_acima_de_2s_fica_ambar():
    ok = OR.faixa_saude(_ordens(), atraso_ms=1900, agora=AGORA)
    lento = OR.faixa_saude(_ordens(), atraso_ms=2600, agora=AGORA)

    def tom(f):
        return next(classes(x) for x in todos(f)
                    if "ord-saude-v" in classes(x) and "s" in textos(x)
                    and "," in textos(x))
    assert "ambar" not in tom(ok)
    assert "ambar" in tom(lento)


def test_saude_sem_estado_das_ordens_nao_quebra():
    t = textos(OR.faixa_saude({}, agora=AGORA))
    assert "MT5" in t and "None" not in t


def test_saude_algo_desligado_fica_rosa():
    o = _ordens(conta={**_ordens()["conta"], "algo": False})
    algo = [x for x in todos(OR.faixa_saude(o, agora=AGORA))
            if "ord-saude-v" in classes(x) and "desligado" in textos(x)]
    assert algo and "rosa" in classes(algo[0])


# ------------------------------------------------------- faixa de chamados
def _chamado(**mudar):
    c = {"chave": "saida_pendente:222", "tipo": "saida_pendente",
         "texto": "saída pendente há mais de 2 min (tentativa 9)",
         "ligacao_id": 8, "ticket": 222, "desde": "2026-10-14T14:35:00",
         "entry_ts": None}
    c.update(mudar)
    return c


def test_sem_chamado_nao_ha_faixa():
    assert OR.faixa_chamados(_ordens(), NOMES) is None


def test_chamado_tem_os_dois_botoes_com_os_ids():
    f = OR.faixa_chamados(_ordens(chamados=[_chamado()]), NOMES)
    t = textos(f)
    assert "precisa de você" in t and "variante-medias-abertura-M7" in t
    ids = [x.id for x in todos(f) if isinstance(getattr(x, "id", None), dict)]
    assert {"type": "av-op-ord-acao", "acao": "encerrar", "id": 222} in ids
    assert {"type": "av-op-ord-acao", "acao": "manter",
            "id": "saida_pendente:222@2026-10-14T14:35:00"} in ids


def test_chamado_escondido_some_e_reaberto_volta():
    o = _ordens(chamados=[_chamado()])
    chave = "saida_pendente:222@2026-10-14T14:35:00"
    assert OR.faixa_chamados(o, NOMES, escondidos=[chave]) is None
    # o mesmo chamado aberto de novo (outra hora) é outro: aparece
    o2 = _ordens(chamados=[_chamado(desde="2026-10-14T14:50:00")])
    assert OR.faixa_chamados(o2, NOMES, escondidos=[chave]) is not None


def test_chamado_sem_ticket_nao_tem_encerrar():
    f = OR.faixa_chamados(_ordens(chamados=[_chamado(
        chave="algo_desligado", tipo="algo_desligado", ticket=None,
        ligacao_id=None, texto="Algo Trading desligado no MT5")]), NOMES)
    acoes = [x.id["acao"] for x in todos(f)
             if isinstance(getattr(x, "id", None), dict)]
    assert acoes == ["manter"]
    assert "automação" in textos(f)


def test_chamado_armado_pede_confirmacao():
    f = OR.faixa_chamados(_ordens(chamados=[_chamado()]), NOMES,
                          armado="encerrar:222")
    assert "Confirmar" in textos(f)


def test_comando_esperando_a_captura():
    f = OR.faixa_chamados(_ordens(), NOMES, esperando=True)
    assert "comando enviado, esperando a captura — o stop e o alvo seguem " \
           "na corretora" in textos(f)


# -------------------------------------------------------- posições abertas
def test_posicoes_confere_e_saida_pendente_com_tentativas_e_tempo():
    tab = OR.posicoes_abertas(_ordens(), NOMES, TICK, agora=AGORA)
    linhas = [x for x in todos(tab) if type(x).__name__ == "Tr"][1:]
    assert len(linhas) == 2
    canal, medias = textos(linhas[0]), textos(linhas[1])
    assert "variante-canal-M7" in canal and "confere" in canal
    # tentativa 3, pendente desde 14:37:06 -> 6 s
    assert "saída pendente — tentando (3ª) · 0:06" in medias


def test_posicoes_ticks_ate_stop_e_alvo_e_resultado():
    tab = OR.posicoes_abertas(_ordens(), NOMES, TICK, agora=AGORA)
    t = textos([x for x in todos(tab) if type(x).__name__ == "Tr"][1])
    # preço agora = 189010 + 94 / (2 × 0,20) = 189245
    # até o stop: (189245 − 188645) / 5 = 120 ticks; alvo: (189665 − 189245)/5 = 84
    assert "120 ticks" in t and "84 ticks" in t
    assert "+47 ticks" in t and "+R$ 94" in t
    assert "✓" in t


def test_venda_nao_usa_a_cor_rosa():
    tab = OR.posicoes_abertas(_ordens(), NOMES, TICK, agora=AGORA)
    lados = [x for x in todos(tab) if "ord-lado" in classes(x)]
    venda = next(x for x in lados if textos(x) == "VENDA")
    compra = next(x for x in lados if textos(x) == "COMPRA")
    assert "ord-lado-v" in classes(venda) and "ord-lado-c" in classes(compra)
    for proibida in ("neg", "rosa", "op-v"):
        assert proibida not in classes(venda).split()


def test_posicao_indisponivel():
    o = _ordens()
    o["ligacoes"]["7"]["desejado"] = "indisponivel"
    t = textos(OR.posicoes_abertas(o, NOMES, TICK, agora=AGORA))
    assert "indisponível" in t


def test_posicao_com_contratos_diferentes_do_esperado():
    o = _ordens()
    o["ligacoes"]["7"]["contratos"] = 1
    t = textos(OR.posicoes_abertas(o, NOMES, TICK, agora=AGORA))
    assert "esperado 1" in t and "diferente" in t


def test_posicoes_de_outro_portfolio_nao_aparecem():
    t = textos(OR.posicoes_abertas(_ordens(), {7: "so-esta"}, TICK, agora=AGORA))
    assert "so-esta" in t and "#8" not in t and "medias" not in t


def test_posicoes_vazias_explicam_sem_demo():
    t = textos(OR.posicoes_abertas(_ordens(n_demo=0, ligacoes={}), NOMES, TICK,
                                   agora=AGORA))
    assert "nenhuma variante na fase demo" in t
    t2 = textos(OR.posicoes_abertas({}, NOMES, TICK, agora=AGORA))
    assert "nenhuma posição" in t2 and "None" not in t2


# -------------------------------------------------------------- três números
def _barra(o):
    n = OR.numeros(o, 0.0, 0.0, portfolio_id=1, ligacoes=[7, 8])
    return next(x for x in todos(n) if "ord-barra-uso" in classes(x))


@pytest.mark.parametrize("perda,tom", [(0.0, "cinza"), (299.0, "cinza"),
                                       (300.0, "ambar"), (424.0, "ambar"),
                                       (425.0, "rosa"), (480.0, "rosa")])
def test_barra_da_perda_muda_de_cor_nos_60_e_85(perda, tom):
    o = _ordens(perda={**_ordens()["perda"], "total": perda})
    assert f"ord-barra-{tom}" in classes(_barra(o))


def test_barra_tem_a_marca_dos_90():
    n = OR.numeros(_ordens(), 0.0, 0.0, portfolio_id=1, ligacoes=[7, 8])
    mk = next(x for x in todos(n) if "ord-barra-marca" in classes(x))
    assert mk.style["left"] == "90%"


def test_perda_da_conta_aberta_em_tres_partes():
    t = textos(OR.numeros(_ordens(), 0.0, 0.0, portfolio_id=1, ligacoes=[7, 8]))
    assert "da conta" in t
    assert "R$ 164" in t and "de R$ 500" in t
    # este portfólio = o dele no por_portfolio; outros = automação menos ele
    assert "este portfólio R$ 100" in t
    assert "outros portfólios R$ 40" in t
    assert "fora da automação R$ 24" in t


def test_numeros_resultado_e_posicoes():
    n = OR.numeros(_ordens(), 361.0, 190.0, portfolio_id=1, ligacoes=[7, 8])
    t = textos(n)
    assert "+R$ 361" in t and "papel no mesmo tamanho: +R$ 190" in t
    assert "1 confere" in t
    assert len(_dicas(n)) == 3


def test_numeros_sem_limite_e_sem_estado():
    t = textos(OR.numeros(_ordens(limite=None), 0.0, 0.0, portfolio_id=1,
                          ligacoes=[7]))
    assert "sem limite" in t
    t2 = textos(OR.numeros({}, 0.0, 0.0, portfolio_id=1, ligacoes=[]))
    assert "None" not in t2 and "—" in t2


# --------------------------------------------------------- operações demo
def _linha(**mudar):
    l = {"ligacao_id": 7, "variante": "variante-canal-M7", "cor": 0,
         "entry_ts": datetime(2026, 10, 14, 10, 15),
         "exit_ts": datetime(2026, 10, 14, 10, 58), "lado": -1, "contratos": 2,
         "preco_entrada": 188205, "preco_saida": 188580,
         "derrapagem_entrada": 2.0, "derrapagem_saida": 1.0, "pontos": -375,
         "resultado": -150.0, "situacao": "fechada",
         "saida_motivo": "stop na corretora", "nota": None, "pedido": None,
         "papel_liquido": -140.0, "mesmo_minuto": True}
    l.update(mudar)
    return l


def test_tabela_demo_tem_as_colunas_e_dica_na_derrapagem():
    tab = OR.operacoes_demo([_linha()])
    t = textos(tab)
    for col in ("Entrada", "Saída", "Variante", "Lado", "Contr.",
                "Preço entrada", "Preço saída", "Derrapagem além do plano (ticks)",
                "Pontos",
                "Resultado", "Situação"):
        assert col in t
    assert "stop na corretora" in t and "-R$ 150" in t
    th = next(x for x in todos(tab) if type(x).__name__ == "Th"
              and "Derrapagem" in textos(x))
    assert _dicas(th)


def test_derrapagem_por_ponta_em_ticks():
    t = textos(OR.operacoes_demo([_linha()]))
    assert "2 · 1" in t        # entrada · saída


def test_situacoes_traduzidas():
    casos = [
        (_linha(situacao="fechada", saida_motivo="sinal",
                nota="saiu na 3ª tentativa (mercado em leilão, 6 s)"),
         ["sinal", "saiu na 3ª tentativa (mercado em leilão, 6 s)"]),
        (_linha(situacao="recusada_perdida", exit_ts=None, contratos=None),
         ["entrada recusada · perdida"]),
        (_linha(situacao="fora_do_ar", exit_ts=None),
         ["não executada · automação fora do ar"]),
        (_linha(situacao="seria_enviada", exit_ts=None,
                pedido="VENDA 2 WINV26 · stop 188.575 · alvo 187.495"),
         ["seria enviada", "VENDA 2 WINV26 · stop 188.575 · alvo 187.495"]),
        (_linha(situacao="aberta", exit_ts=None), ["aberta"]),
    ]
    for linha, esperados in casos:
        t = textos(OR.operacoes_demo([linha]))
        for e in esperados:
            assert e in t, (e, t)


def test_tabela_demo_venda_nao_rosa():
    tab = OR.operacoes_demo([_linha()])
    venda = next(x for x in todos(tab)
                 if "ord-lado" in classes(x) and textos(x) == "VENDA")
    assert "ord-lado-v" in classes(venda)
    for proibida in ("neg", "rosa", "op-v"):
        assert proibida not in classes(venda).split()


def test_tabela_demo_vazia_explica():
    t = textos(OR.operacoes_demo([]))
    assert "nenhuma operação na demo" in t


# ------------------------------------------------------------ diário do dia
def _ev(hora, tipo, lig=7, **mais):
    e = {"quando": datetime.fromisoformat(f"2026-10-14T{hora}"), "tipo": tipo,
         "ligacao_id": lig}
    e.update(mais)
    return e


EVENTOS = [
    _ev("09:21:00", "perdida", motivo="automação fora do ar"),
    _ev("09:56:01", "recusada", lado=-1, motivo="preço fora do limite"),
    _ev("10:15:00", "enviando", lado=1, contratos=2),
    _ev("10:15:01", "executada", lado=1, contratos=2, preco=188335,
        simbolo="WINV26", atraso_ms=700),
    _ev("10:15:01", "protecao_enviando"),
    _ev("10:15:01", "protecao", stop_px=188035, alvo_px=188935),
    _ev("11:42:01", "saida_recusada", motivo="mercado em leilão"),
    _ev("11:42:07", "saida_executada", preco=188420, contratos=2),
    _ev("12:00:00", "comando", lig=None, motivo="zerar_tudo_cumprido"),
    _ev("12:00:01", "comando", lig=None, motivo="envio_cumprido"),
    _ev("12:01:00", "cancelar_enviando", ticket=5),
    _ev("12:01:00", "cancelar_recusada", ticket=5),
    _ev("13:00:00", "chamado", lig=None, motivo="Algo Trading desligado no MT5"),
    _ev("13:05:00", "comando", lig=None, motivo="zerar_tudo"),
    _ev("13:06:00", "conta_travada", lig=None, perda=452.0, limite=500.0),
]


def _linhas_diario(d):
    return [x for x in todos(d) if "ord-ev" in classes(x).split()]


def test_diario_esconde_eventos_internos_e_traduz():
    d = OR.diario_do_dia(EVENTOS, NOMES)
    t = textos(d)
    for interno in ("enviando", "cumprido", "cancelar", "protecao_enviando"):
        assert interno not in t
    assert "COMPRA 2 WINV26 executada a 188.335 em 0,7 s" in t
    assert "saída executada a 188.420" in t
    assert "Zerar tudo" in t
    assert "automação" in t
    # mais novo primeiro
    assert textos(_linhas_diario(d)[0]).startswith("13:06:00")


def test_diario_so_problemas():
    d = OR.diario_do_dia(EVENTOS, NOMES, so_problemas=True)
    tipos_vistos = textos(d)
    assert "executada a 188.335" not in tipos_vistos
    assert "saída executada" not in tipos_vistos
    assert "Zerar tudo" not in tipos_vistos
    # recusada, perdida, saída recusada, chamado, conta travada
    assert len(_linhas_diario(d)) == 5


def test_diario_vazio_explica():
    assert "nada" in textos(OR.diario_do_dia([], NOMES))
    assert "nenhum problema" in textos(OR.diario_do_dia(
        [_ev("10:15:01", "executada", preco=1, contratos=1, lado=1)], NOMES,
        so_problemas=True))


# ---------------------------------------------------------------- avaliação
def test_selo_backtest_ok():
    t = textos(OR.selo_backtest({"pregoes": 5, "operacoes": 14, "diferencas": 0,
                                 "ok": True, "lista": []}))
    assert "papel = backtest ✓ (5 pregões, 14 operações)" in t


def test_selo_backtest_com_diferencas_lista():
    s = OR.selo_backtest({"pregoes": 5, "operacoes": 14, "diferencas": 2,
                          "ok": False,
                          "lista": [{"nome": "canal", "dia": date(2026, 10, 9),
                                     "n": 2}]})
    t = textos(s)
    assert "2 diferenças" in t and "canal" in t and "09/10" in t


def test_selo_backtest_sem_pregao():
    t = textos(OR.selo_backtest({"pregoes": 0, "operacoes": 0, "diferencas": 0,
                                 "ok": None, "lista": []}))
    assert "ainda sem pregão conferido" in t


def _cmp():
    return {"pregoes": 5,
            "papel": {"n": 14, "pontos_por_operacao": 221.0, "fator_lucro": 1.71,
                      "derrapagem": 1.0},
            "demo": {"n": 12, "pontos_por_operacao": 208.0, "fator_lucro": 1.58,
                     "mesmo_minuto": 12, "derrapagem": 1.3, "perdidas": 2,
                     "recusadas": 2, "resolvidas": 1, "chamados": 1}}


def test_papel_x_demo_por_contrato_com_dica_em_cada_linha():
    tab = OR.tabela_papel_demo(_cmp())
    t = textos(tab)
    for rot in ("Operações", "Pontos por operação", "Fator de lucro",
                "Sinal no mesmo minuto", "Derrapagem média por ponta",
                "Recusadas · resolvidas sozinha · chamados"):
        assert rot in t
    assert "2 perdidas" in t and "85,7%" in t and "12 de 14" in t
    assert "2 · 1 · 1" in t and "+0,3" in t
    assert len(_dicas(tab)) == 6


def test_papel_x_demo_vazio_explica():
    t = textos(OR.tabela_papel_demo({"pregoes": 0, "papel": None, "demo": None}))
    assert "nenhum pregão na demo ainda" in t


def test_avaliacao_e_recolhivel_e_leva_a_curva():
    from dash import html
    curva = html.Div("CURVA", id="curva-teste")
    a = OR.avaliacao({"pregoes": 0, "operacoes": 0, "diferencas": 0, "ok": None,
                      "lista": []}, {"pregoes": 0, "papel": None, "demo": None},
                     curva=curva)
    assert type(a).__name__ == "Details"
    ids = {getattr(x, "id", None) for x in todos(a)}
    assert {"av-op-ord-selo", "av-op-ord-cmp", "curva-teste"} <= ids


# -------------------------------------------------- editor de contratos
def test_custo_do_stop_texto():
    t = textos(OR.custo_stop_texto(3, {"reais": 180.0, "pct_limite": 36.0}))
    assert "R$ 180" in t and "36%" in t
    assert "vale a partir da próxima operação" in textos(OR.editor_contratos())
    t2 = textos(OR.custo_stop_texto(3, {"reais": None, "pct_limite": None}))
    assert "None" not in t2


def test_editor_de_contratos_campo_de_texto_numerico():
    campo = next(x for x in todos(OR.editor_contratos())
                 if getattr(x, "id", None) == "av-op-ord-ctr-valor")
    assert campo.type == "text" and campo.inputMode == "numeric"


def test_ler_contratos():
    assert OR.ler_contratos("3") == 3
    assert OR.ler_contratos(" 2 ") == 2
    assert OR.ler_contratos("") is None
    for ruim in ("0", "-1", "1,5", "abc"):
        with pytest.raises(ValueError):
            OR.ler_contratos(ruim)


# ======================================================================
# Leituras novas do core: operacoes_demo e comparativo_demo
# ======================================================================
DIA = date(2026, 10, 14)


def _ts(hhmm: str, dia: date = DIA) -> datetime:
    return datetime.fromisoformat(f"{dia} {hhmm}")


def _evento(con, n, quando, tipo, lig, entry=None, *, dia=DIA, **campos):
    colunas = ("lado", "contratos", "simbolo", "ticket", "retcode",
               "preco_papel", "preco", "atraso_ms", "tentativa", "motivo")
    dados = {k: v for k, v in campos.items() if k not in colunas}
    con.execute(
        "INSERT INTO ordens_eventos (evento_id, quando, tipo, conta_id, "
        "ligacao_id, entry_ts, lado, contratos, simbolo, ticket, retcode, "
        "preco_papel, preco, atraso_ms, tentativa, motivo, dados) "
        "VALUES (?,?,?,3,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [f"demo-{dia:%Y%m%d}-{n:06d}", _ts(quando, dia), tipo, lig,
         None if entry is None else _ts(entry, dia),
         *[campos.get(c) for c in colunas],
         json.dumps(dados) if dados else None])


def _papel(con, lig, entrada, saida, side, entry_px, exit_px, liquido,
           dia=DIA, contratos=1):
    pts = (exit_px - entry_px) * side
    con.execute(
        "INSERT INTO papel_operacoes (op_id, ligacao_id, plano_id, dia, "
        "entry_ts, exit_ts, side, contratos, entry_px, exit_px, points, bruto, "
        "custo, liquido, reason, aberta, conta, calculado_em) VALUES "
        "(nextval('seq_papel_op'),?,1,?,?,?,?,?,?,?,?,?,0,?,2,false,true,?)",
        [lig, dia, _ts(entrada, dia), _ts(saida, dia), side, contratos,
         entry_px, exit_px, pts, liquido, liquido, _ts("18:00", dia)])


@pytest.fixture
def demo(banco):
    """Portfólio 1 com a ligação 7 ("canal"); a 9 é de outro portfólio.

    Compra (lig 7, 10:15): papel entra 188.330 e sai 188.420 (+90);
      demo executa a 188.340 (pior: +10 pts = +2 ticks) e sai a 188.410
      (pior: papel 188.420 − demo 188.410 = 10 × (+1) = +2 ticks).
    Venda (lig 7, 11:05): papel entra 188.205 e sai 188.580 (stop, −375);
      demo executa a 188.200 (vendeu 5 pts mais barato = pior: (188.200 −
      188.205) × (−1) / 5 = +1 tick) e sai a 188.590 no stop da corretora
      (comprou 10 mais caro = pior: (188.580 − 188.590) × (−1) / 5 = +2).
    Venda (lig 7, 13:00): demo executou MELHOR que o papel na entrada:
      papel 188.000, demo 188.010 → (188.010 − 188.000) × (−1)/5 = −2 ticks.
    09:56: entrada recusada e perdida. 09:21: perdida (automação fora do ar).
    """
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em, "
                    "ligado) VALUES (1, 'pf', '2026-09-01', true), "
                    "(2, 'outro', '2026-09-01', true)")
        for vid, nome in ((1, "canal"), (2, "outra")):
            con.execute("INSERT INTO estrategia_variantes (variante_id, "
                        "estrategia, nome, criado_em) VALUES (?,?,?,?)",
                        [vid, "rompimento_canal", nome, "2026-09-01"])
        for lig, pf, vid in ((7, 1, 1), (9, 2, 2)):
            con.execute("INSERT INTO portfolio_membros (ligacao_id, "
                        "portfolio_id, variante_id, adicionado_em, fase, "
                        "fase_desde, ligada) VALUES (?,?,?,'2026-09-01',"
                        "'demo','2026-10-01',true)", [lig, pf, vid])
        con.execute(
            "INSERT INTO planos_operacao (plano_id, wfa_id, symbol, strategy, "
            "variante_id, estado, vale_a_partir, contratos, profile, "
            "created_at) VALUES (1, 1, 'WIN$N', 'rompimento_canal', 1, 'ativo', "
            "'2026-09-01', 1, '{\"slippage_ticks\": 2}', '2026-09-01')")
        _papel(con, 7, "10:15", "10:40", 1, 188330, 188420, 18.0)
        # o plano opera 2 contratos aqui; a demo, 1 (o papel no tamanho da
        # demo é a metade do bruto)
        _papel(con, 7, "11:05", "11:42", -1, 188205, 188580, -150.0,
               contratos=2)
        _papel(con, 7, "13:00", "13:20", -1, 188000, 187900, 20.0)
        _papel(con, 7, "09:56", "10:05", -1, 188100, 188000, 20.0)
        n = iter(range(1, 100))
        _evento(con, next(n), "09:21:31", "perdida", 7, "09:21",
                motivo="automação fora do ar")
        _evento(con, next(n), "09:56:00", "enviando", 7, "09:56", lado=-1,
                contratos=1, preco_papel=188100, tentativa=1)
        _evento(con, next(n), "09:56:01", "recusada", 7, "09:56",
                motivo="preço fora do limite")
        _evento(con, next(n), "09:56:31", "perdida", 7, "09:56",
                motivo="preço fora do limite")
        _evento(con, next(n), "10:15:00", "enviando", 7, "10:15", lado=1,
                contratos=1, preco_papel=188330, tentativa=1,
                stop_px=188030, alvo_px=188930)
        _evento(con, next(n), "10:15:01", "executada", 7, "10:15", lado=1,
                contratos=1, preco_papel=188330, preco=188340, ticket=111,
                atraso_ms=700)
        _evento(con, next(n), "10:40:00", "saida_enviando", 7, ticket=111,
                lado=1, contratos=1, tentativa=1, motivo="papel zerado")
        _evento(con, next(n), "10:40:01", "saida_recusada", 7, ticket=111,
                motivo="mercado em leilão")
        _evento(con, next(n), "10:40:03", "saida_enviando", 7, ticket=111,
                lado=1, contratos=1, tentativa=2, motivo="papel zerado")
        _evento(con, next(n), "10:40:06", "saida_executada", 7, ticket=111,
                lado=1, contratos=1, preco=188410, motivo="papel zerado")
        _evento(con, next(n), "11:05:00", "enviando", 7, "11:05", lado=-1,
                contratos=1, preco_papel=188205, tentativa=1)
        _evento(con, next(n), "11:05:01", "executada", 7, "11:05", lado=-1,
                contratos=1, preco_papel=188205, preco=188200, ticket=112,
                atraso_ms=900)
        _evento(con, next(n), "11:42:02", "saiu_antes", 7, ticket=112,
                motivo="stop na corretora", preco=188590, contratos=1)
        _evento(con, next(n), "13:00:00", "enviando", 7, "13:00", lado=-1,
                contratos=1, preco_papel=188000, tentativa=1)
        _evento(con, next(n), "13:01:10", "executada", 7, "13:00", lado=-1,
                contratos=1, preco_papel=188000, preco=188010, ticket=113)
        _evento(con, next(n), "13:30:00", "chamado", 7, motivo="teste",
                ticket=113)
        # de outro portfólio: não entra
        _evento(con, next(n), "10:15:00", "enviando", 9, "10:15", lado=1,
                contratos=1, preco_papel=1, tentativa=1)
    return banco


def _ler(fn):
    with db.connect(read_only=True) as con:
        return fn(con)


def test_operacoes_demo_casa_evento_e_papel_pela_chave(demo):
    ops = _ler(lambda con: PL.operacoes_demo(con, 1, DIA))
    assert [o["ligacao_id"] for o in ops] == [7] * 5
    por = {o["entry_ts"].strftime("%H:%M"): o for o in ops}
    assert set(por) == {"09:21", "09:56", "10:15", "11:05", "13:00"}
    c = por["10:15"]
    assert (c["preco_entrada"], c["preco_saida"], c["contratos"]) == (
        188340, 188410, 1)
    assert c["pontos"] == 70 and c["resultado"] == pytest.approx(14.0)
    assert c["papel_liquido"] == pytest.approx(18.0)
    assert c["situacao"] == "fechada" and c["saida_motivo"] == "sinal"
    assert c["nota"] == "saiu na 2ª tentativa (mercado em leilão, 6 s)"
    assert c["variante"] == "canal" and c["mesmo_minuto"] is True


def test_derrapagem_compra_nas_duas_pontas(demo):
    c = next(o for o in _ler(lambda con: PL.operacoes_demo(con, 1, DIA))
             if o["entry_ts"] == _ts("10:15"))
    assert c["derrapagem_entrada"] == pytest.approx(2.0)
    assert c["derrapagem_saida"] == pytest.approx(2.0)


def test_derrapagem_venda_nas_duas_pontas(demo):
    v = next(o for o in _ler(lambda con: PL.operacoes_demo(con, 1, DIA))
             if o["entry_ts"] == _ts("11:05"))
    assert v["derrapagem_entrada"] == pytest.approx(1.0)
    assert v["derrapagem_saida"] == pytest.approx(2.0)
    assert v["situacao"] == "fechada" and v["saida_motivo"] == "stop na corretora"
    assert v["pontos"] == -390


def test_derrapagem_a_favor_e_negativa(demo):
    v = next(o for o in _ler(lambda con: PL.operacoes_demo(con, 1, DIA))
             if o["entry_ts"] == _ts("13:00"))
    assert v["derrapagem_entrada"] == pytest.approx(-2.0)
    assert v["situacao"] == "aberta" and v["mesmo_minuto"] is False


def test_operacoes_demo_perdidas(demo):
    por = {o["entry_ts"].strftime("%H:%M"): o
           for o in _ler(lambda con: PL.operacoes_demo(con, 1, DIA))}
    assert por["09:21"]["situacao"] == "fora_do_ar"
    assert por["09:56"]["situacao"] == "recusada_perdida"
    assert por["09:56"]["preco_entrada"] is None


def test_operacoes_demo_seria_enviada(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'pf', '2026-09-01')")
        con.execute("INSERT INTO estrategia_variantes (variante_id, estrategia, "
                    "nome, criado_em) VALUES (1,'rompimento_canal','canal',"
                    "'2026-09-01')")
        con.execute("INSERT INTO portfolio_membros (ligacao_id, portfolio_id, "
                    "variante_id, adicionado_em, fase, fase_desde, ligada) "
                    "VALUES (7,1,1,'2026-09-01','demo','2026-10-01',true)")
        _evento(con, 1, "10:15:01", "seria_enviada", 7, "10:15", lado=-1,
                contratos=2, simbolo="WINV26", preco_papel=188205,
                stop_px=188575, alvo_px=187495)
    o = _ler(lambda con: PL.operacoes_demo(con, 1, DIA))[0]
    assert o["situacao"] == "seria_enviada"
    assert o["pedido"] == "VENDA 2 WINV26 · stop 188.575 · alvo 187.495"


def test_operacoes_demo_sem_demo_e_lista_vazia(banco):
    with db.connect_write() as con:
        con.execute("INSERT INTO portfolios (portfolio_id, nome, criado_em) "
                    "VALUES (1, 'pf', '2026-09-01')")
    assert _ler(lambda con: PL.operacoes_demo(con, 1, DIA)) == []
    c = _ler(lambda con: PL.comparativo_demo(con, 1, dia=DIA))
    assert c["pregoes"] == 0 and c["demo"] is None


def test_comparativo_demo(demo):
    c = _ler(lambda con: PL.comparativo_demo(con, 1, dia=DIA))
    assert c["pregoes"] == 1
    # papel: as 4 operações fechadas da ligação 7 no dia
    assert c["papel"]["n"] == 4
    # demo fechadas: +70 e −390 → média −160 pts
    d = c["demo"]
    assert d["n"] == 2 and d["pontos_por_operacao"] == pytest.approx(-160.0)
    assert d["fator_lucro"] == pytest.approx(70 / 390)
    # além do plano, por ponta: 2, 2 (compra) · 1, 2 (venda) · −2 (aberta,
    # só a entrada) = 5/5 = 1. O plano supõe 2 ticks por ponta: papel 2,
    # demo absoluta 1 + 2 = 3, diferença = o além = 1
    assert d["derrapagem_extra"] == pytest.approx(1.0)
    assert c["papel"]["derrapagem"] == pytest.approx(2.0)
    assert d["derrapagem"] == pytest.approx(3.0)
    # mesmo minuto: 10:15 e 11:05 (13:00 executou 13:01)
    assert d["mesmo_minuto"] == 2
    assert d["perdidas"] == 2
    assert (d["recusadas"], d["resolvidas"], d["chamados"]) == (1, 0, 1)


def test_situacao_backtest_do_portfolio(demo):
    with db.connect_write() as con:
        con.execute("INSERT INTO papel_backtest (ligacao_id, dia, conferido_em, "
                    "ok, n_papel, n_backtest, diferencas) VALUES "
                    "(7, '2026-10-09', '2026-10-10 09:00', false, 3, 3, ?), "
                    "(7, '2026-10-10', '2026-10-11 09:00', true, 2, 2, ?)",
                    [json.dumps({"operacoes": [{}, {}]}),
                     json.dumps({"operacoes": []})])
    s = _ler(lambda con: PL.situacao_backtest(con, 1, DIA))
    assert (s["pregoes"], s["operacoes"], s["diferencas"], s["ok"]) == (
        2, 5, 2, False)
    assert s["lista"] == [{"nome": "canal", "dia": date(2026, 10, 9), "n": 2}]


def test_variantes_trazem_os_contratos_da_demo(demo):
    with db.connect_write() as con:
        con.execute("UPDATE portfolio_membros SET contratos_demo = 3 "
                    "WHERE ligacao_id = 7")
    vs = _ler(lambda con: PL.variantes(con, 1, DIA, hoje=DIA))
    assert vs[0]["contratos_demo"] == 3


# ======================================================================
# Callbacks: o pulso não abre o banco; chamados; editor de contratos
# ======================================================================
def _estado_captura(ordens):
    return {"atualizado_em": "2026-10-14T14:37:11", "ultimo_salvo":
            "2026-10-14T14:36:00", "em_pregao": True, "ordens": ordens}


VARS = [{"ligacao_id": 7, "nome": "variante-canal-M7", "cor": 0,
         "contratos": 1, "contratos_demo": 2, "fase": "demo"},
        {"ligacao_id": 8, "nome": "variante-medias-abertura-M7", "cor": 1,
         "contratos": 1, "contratos_demo": None, "fase": "demo"}]


def test_pulso_das_ordens_nao_abre_o_banco(monkeypatch):
    from dash import no_update
    from ui import callbacks_operacao as CO

    def explode(*a, **k):
        raise AssertionError("o pulso abriu o banco")
    monkeypatch.setattr(db, "connect", explode)
    monkeypatch.setattr(db, "connect_write", explode)
    est = _estado_captura(_ordens(chamados=[_chamado()]))
    dados = {"pid": 1, "realizado": 267.0, "papel": 190.0, "atraso_ms": 700}
    out = CO.pulso_ordens(est, None, VARS, 1, dados, [], [], None, AGORA,
                          1000.0)
    saude, chamados, posicoes, numeros, versao = out
    assert "0,7 s" in textos(saude)
    assert "precisa de você" in textos(chamados)
    assert "confere" in textos(posicoes)
    # 267 realizado + 94 − 10 abertos = 351
    assert "+R$ 351" in textos(numeros)
    assert versao == "2026-10-14T14:30:02"
    # a mesma marca de novo: nada de reler o banco
    assert CO.pulso_ordens(est, "2026-10-14T14:30:02", VARS, 1, dados, [], [],
                           None, AGORA, 1000.0)[4] is no_update


def test_pulso_ignora_dados_de_outro_portfolio():
    from ui import callbacks_operacao as CO
    est = _estado_captura(_ordens())
    out = CO.pulso_ordens(est, None, VARS, 2, {"pid": 1, "realizado": 999.0,
                                                "papel": 0, "atraso_ms": None},
                          [], [], None, AGORA, 1000.0)
    assert "999" not in textos(out[3])


def test_pulso_sem_captura_mostra_comando_esperando():
    from ui import callbacks_operacao as CO
    est = _estado_captura(_ordens(chamados=[_chamado()]))
    est["atualizado_em"] = "2026-10-14T14:30:00"      # parada há 7 min
    out = CO.pulso_ordens(est, None, VARS, 1, {}, [], [990.0], None, AGORA,
                          1000.0)
    t = textos(out[1])
    assert "esperando a captura" in t
    # o chamado gravado é de quando a captura parou: não aparece
    assert "precisa de você" not in t


def test_pulso_tudo_no_papel_nao_quebra():
    from ui import callbacks_operacao as CO
    est = _estado_captura({"foto": None, "parado": "fora do pregão",
                           "vivo_em": "2026-10-14T14:37:10", "n_demo": 0,
                           "envio": False, "travada": None, "chamados": []})
    out = CO.pulso_ordens(est, None, VARS, 1, {}, [], [], None, AGORA, 1000.0)
    t = textos(out)
    assert "None" not in t and "nenhuma variante na fase demo" in t


def test_encerrar_posicao_dois_cliques_escreve_o_comando(monkeypatch, tmp_path):
    from core import comandos
    from ui import callbacks_operacao as CO
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "cmd")
    armado, esc, env, aviso = CO.acao_chamado("encerrar", 222, None, [], [], 100.0)
    assert armado == {"chave": "encerrar:222", "em": 100.0}
    assert not (tmp_path / "cmd").exists()
    # segundo clique depois de 6 s: só rearma
    armado2, *_ = CO.acao_chamado("encerrar", 222, armado, [], [], 107.0)
    assert armado2["em"] == 107.0 and not (tmp_path / "cmd").exists()
    armado3, esc, env, aviso = CO.acao_chamado("encerrar", 222, armado2, [], [],
                                               110.0)
    assert armado3 is None and env == [110.0] and "enviado" in aviso
    cmds = comandos.consumir(tmp_path / "cmd")
    assert [(c["tipo"], c["ticket"]) for c in cmds] == [("encerrar_posicao", 222)]


def test_manter_so_esconde_sem_comando(monkeypatch, tmp_path):
    from core import comandos
    from ui import callbacks_operacao as CO
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "cmd")
    chave = "saida_pendente:222@2026-10-14T14:35:00"
    armado, esc, env, _ = CO.acao_chamado("manter", chave, None, [], [], 1.0)
    assert esc == [chave] and env == [] and armado is None
    assert not (tmp_path / "cmd").exists()


def test_editor_de_contratos_abre_com_o_valor_e_salva(banco, monkeypatch):
    from ui import callbacks_operacao as CO
    estilo, alvo, valor, titulo, antes = CO.abrir_editor(7, VARS)
    assert estilo["display"] != "none" and alvo == 7 and valor == "2"
    assert "variante-canal-M7" in titulo and "antes: 2" in antes
    gravados = []
    monkeypatch.setattr(CO.AV, "definir_contratos",
                        lambda lig, n, **k: gravados.append((lig, n, k)))
    # o banco ocupado não segura a tela: 2 tentativas, como o Zerar tudo
    assert CO.salvar_editor(7, "3")[0] and gravados == [(7, 3, {"tentativas": 2})]
    assert CO.salvar_editor(7, "")[0] and gravados[-1][:2] == (7, None)
    ok, msg = CO.salvar_editor(7, "1,5")
    assert not ok and "inteiro" in msg and len(gravados) == 2


def test_quem_le_o_diario_das_ordens_nao_ouve_o_pulso(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 "
                    "09:00:00', 100, 101, 99, 100, 1)")
    from ui.app import build
    app = build()
    cb = next(c for c in app.callback_map.values()
              if getattr(c.get("callback"), "__name__", "") == "ordens_op")
    entradas = {f"{e['id']}.{e['property']}" for e in cb["inputs"]}
    assert "av-op-ord-versao.data" in entradas
    assert "av-op-intervalo.n_intervals" not in entradas


# ======================================================================
# Rodada de correção 1
# ======================================================================
def test_operacao_traz_a_derrapagem_do_plano_e_o_papel_no_tamanho_da_demo(demo):
    por = {o["entry_ts"].strftime("%H:%M"): o
           for o in _ler(lambda con: PL.operacoes_demo(con, 1, DIA))}
    # o perfil do plano 1 supõe 2 ticks por ponta
    assert por["10:15"]["slippage_plano"] == pytest.approx(2.0)
    # sem operação no papel (09:21): o plano em vigor da ligação
    assert por["09:21"]["slippage_plano"] == pytest.approx(2.0)
    # bruto 18 com 1 contrato no plano, 1 na demo
    assert por["10:15"]["papel_mesmo_tamanho"] == pytest.approx(18.0)
    # bruto −150 com 2 no plano, 1 na demo: −75
    assert por["11:05"]["papel_mesmo_tamanho"] == pytest.approx(-75.0)
    # não executada: sem par no tamanho da demo
    assert por["09:56"]["papel_mesmo_tamanho"] is None


def test_dados_da_demo_comparam_bruto_com_bruto_no_mesmo_tamanho(demo):
    from ui import callbacks_operacao as CO
    ops, evs = _ler(lambda con: (PL.operacoes_demo(con, 1, DIA),
                                 PL.eventos_ordens(con, 1, DIA)))
    d = CO.dados_demo(ops, evs, 1)
    # realizado da demo: +70 pts (14) e −390 pts (−78) → −64
    assert d["realizado"] == pytest.approx(-64.0)
    # papel das executadas no tamanho da demo: 18 − 75 + 20 = −37
    assert d["papel"] == pytest.approx(-37.0)
    assert d["atraso_ms"] == pytest.approx(800.0)


def test_papel_x_demo_mostra_plano_demo_absoluta_e_o_alem():
    c = _cmp()
    c["papel"]["derrapagem"] = 1.0
    c["demo"].update(derrapagem=1.3, derrapagem_extra=0.3)
    tab = OR.tabela_papel_demo(c)
    linha = next(x for x in todos(tab) if type(x).__name__ == "Tr"
                 and "Derrapagem média por ponta" in textos(x))
    t = textos(linha)
    assert "1 tick" in t and "1,3 tick" in t and "+0,3" in t
    dica_ = next(x for x in todos(linha) if "dica-mark" in classes(x))
    assert "perto de 0" in dica_.to_plotly_json()["props"]["data-dica"]


def test_comparativo_de_dia_passado_vem_do_cache(demo, monkeypatch):
    chamadas = []
    original = PL._demo_do_dia

    def contando(con, pid, d):
        chamadas.append(d)
        return original(con, pid, d)
    monkeypatch.setattr(PL, "_demo_do_dia", contando)
    depois = date(2026, 10, 15)
    a = _ler(lambda con: PL.comparativo_demo(con, 1, dia=depois))
    b = _ler(lambda con: PL.comparativo_demo(con, 1, dia=depois))
    assert a == b and chamadas == [DIA]
    # o pregão de hoje (o da tela) nunca vem do cache
    _ler(lambda con: PL.comparativo_demo(con, 1, dia=DIA))
    _ler(lambda con: PL.comparativo_demo(con, 1, dia=DIA))
    assert chamadas == [DIA, DIA, DIA]
    # evento atrasado chegando ao banco muda a impressão: recalcula
    with db.connect_write() as con:
        _evento(con, 90, "16:00:00", "chamado", 7, motivo="atrasado", ticket=113)
    c = _ler(lambda con: PL.comparativo_demo(con, 1, dia=depois))
    assert chamadas[-1] == DIA and len(chamadas) == 4
    assert c["demo"]["chamados"] == 2


def test_dia_no_ganho_mostra_as_partes_com_rotulo():
    o = _ordens(perda={"este": 0.0, "outros": -80.0, "fora": 20.0, "total": 0.0,
                       "por_portfolio": {"1": -80.0}})
    t = textos(OR.numeros(o, 0.0, 0.0, portfolio_id=1, ligacoes=[7, 8]))
    assert "este portfólio ganho R$ 80" in t
    assert "outros portfólios R$ 0" in t and "fora da automação R$ 20" in t
    assert "a barra conta só perdas" in t


def test_ler_contratos_so_digitos_ascii():
    for ruim in ("²", "٣", "３"):
        with pytest.raises(ValueError):
            OR.ler_contratos(ruim)


def test_stop_maior_que_o_limite_avisa_sem_bloquear():
    t = textos(OR.custo_stop_texto(10, {"reais": 600.0, "pct_limite": 120.0}))
    assert "passa do limite do dia" in t
    assert "passa do limite" not in textos(OR.custo_stop_texto(
        3, {"reais": 180.0, "pct_limite": 36.0}))


def test_editor_previa_espera_pouco_pelo_banco(monkeypatch):
    from ui import callbacks_operacao as CO
    pedidos = []
    monkeypatch.setattr(CO.AV, "custo_de_um_stop", lambda lig, n, **k: (
        pedidos.append(k) or {"reais": 60.0, "pct_limite": 12.0}))
    assert "R$ 60" in textos(CO.custo_editor(7, "1"))
    assert pedidos == [{"tentativas": 2}]


def test_envio_com_banco_ocupado(monkeypatch, tmp_path):
    """Desligar escreve o comando antes do banco: ocupado, a captura
    desliga mesmo assim. Ligar precisa do banco. Nenhum dos dois segura a
    tela: 2 tentativas, resposta em menos de 2 s."""
    import time as _t

    from core import comandos
    from ui import callbacks_operacao as CO
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "cmd")
    vistas = []

    def ocupado(tentativas=40, espera=0.25):
        vistas.append(tentativas)
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(db, "connect_write", ocupado)
    t0 = _t.monotonic()
    armado, aviso, feito = CO.acao("envio-desligar", 3, "envio-desligar:3")
    assert _t.monotonic() - t0 < 2
    assert not feito and armado is None
    assert "comando enviado — a captura desliga o envio na próxima volta" in aviso
    assert [(c["tipo"], c["ligado"]) for c in comandos.consumir(tmp_path / "cmd")] \
        == [("envio", False)]
    armado, aviso, feito = CO.acao("envio-ligar", 3, "envio-ligar:3")
    assert aviso == "banco ocupado, tente de novo" and not feito
    assert vistas == [2, 2]


def test_tabela_do_papel_mostra_a_demo_na_mesma_operacao(demo):
    from ui import callbacks_operacao as CO
    from ui.components import operacao_panel as OP
    ops, dem = _ler(lambda con: (PL.operacoes_do_dia(con, 1, DIA, hoje=DIA),
                                 PL.operacoes_demo(con, 1, DIA)))
    tab = OP.tabela_operacoes(CO.juntar_demo(ops, dem))
    linhas = {textos(x).split()[0]: textos(x) for x in todos(tab)
              if type(x).__name__ == "Tr"}
    assert "2 · 2 ticks" in linhas["10:15"]          # além do plano
    assert "2 / 1" in linhas["11:05"]                 # papel 2, demo 1
    assert "não executada" in linhas["09:56"]


def test_trocar_o_filtro_do_diario_nao_refaz_o_comparativo(_banco_isolado):
    with db.connect_write() as con:
        db.init_schema(con)
        con.execute("INSERT INTO instruments (symbol, description) "
                    "VALUES ('WIN$N', 'teste')")
        con.execute("INSERT INTO bars_m1 (symbol, ts, open, high, low, close, "
                    "src_ingest_id) VALUES ('WIN$N', TIMESTAMP '2026-01-05 "
                    "09:00:00', 100, 101, 99, 100, 1)")
    from ui.app import build
    app = build()

    def entradas(nome):
        cb = next(c for c in app.callback_map.values()
                  if getattr(c.get("callback"), "__name__", "") == nome)
        return {f"{e['id']}.{e['property']}" for e in cb["inputs"]}
    assert "av-op-ord-diario-filtro.value" not in entradas("ordens_op")
    assert "av-op-ord-diario-filtro.value" in entradas("diario_op")
