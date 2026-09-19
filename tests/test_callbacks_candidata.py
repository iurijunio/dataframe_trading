"""Testes dos pedaços de `ui/callbacks_candidata.py` que não precisam do
app Dash montado — texto e regras de seleção, extraídos dos callbacks para
poderem ser testados direto.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import candidata  # noqa: E402
from ui import callbacks_candidata as CC  # noqa: E402


def _detalhes(holdout: bool) -> dict:
    return {"strategy": "canal_donchian", "symbol": "WIN$N",
            "is_meses": 12, "oos_meses": 6, "inteligencia": "bayes",
            "holdout": holdout}


# ----------------------------------------------------------------- resumo
def test_texto_resumo_sem_holdout_nao_menciona_holdout():
    assert "holdout" not in CC._texto_resumo(_detalhes(False))


def test_texto_resumo_com_holdout_avisa():
    """A curva de um walk-forward salvo com o holdout inclui esses meses —
    quem lê a tela precisa saber disso."""
    assert "holdout incluído" in CC._texto_resumo(_detalhes(True))


def test_texto_resumo_diz_as_janelas_em_meses():
    """Legível para quem opera: 'IS 12 meses / OOS 6 meses', não 'IS12/OOS6'."""
    texto = CC._texto_resumo(_detalhes(False))
    assert "canal_donchian" in texto and "WIN$N" in texto
    assert "IS 12 meses" in texto and "OOS 6 meses" in texto
    assert "bayes" in texto


# ---------------------------------------------------------------- seletor
def _salvo(wfa_id, nome="teste", quando=datetime(2026, 9, 16, 10, 32)):
    return {"wfa_id": wfa_id, "nome": nome, "is_meses": 12, "oos_meses": 6,
            "quando": quando, "rotulo": "rótulo longo de antes"}


def test_rotulo_curto_so_com_o_que_identifica():
    """O rótulo antigo trazia WFE, janelas positivas e holdout: não cabia no
    seletor e repetia o que o resumo ao lado já diz."""
    r = CC._rotulo_curto(_salvo(8, "romp-canal-est-dd-12-6"))
    assert r == "#8 · romp-canal-est-dd-12-6 · IS 12 / OOS 6 · 16/09"


def test_rotulo_curto_sem_nome():
    assert "sem nome" in CC._rotulo_curto(_salvo(3, nome=None))


def test_valor_mantem_a_escolha_que_ainda_existe():
    """Não troca o que o usuário escolheu só porque abriu outro WFA na aba
    Walk-Forward."""
    assert CC._valor_do_seletor(atual=8, ids={3, 8}, aberto_no_wfa=3) == 8


def test_valor_vazio_herda_o_wfa_aberto_na_outra_aba():
    """Chegando do Walk-Forward, a tela já abre no mesmo walk-forward."""
    assert CC._valor_do_seletor(atual=None, ids={3, 8}, aberto_no_wfa=3) == 3


def test_valor_excluido_herda_o_aberto_ou_limpa():
    assert CC._valor_do_seletor(atual=5, ids={3, 8}, aberto_no_wfa=8) == 8
    assert CC._valor_do_seletor(atual=5, ids={3, 8}, aberto_no_wfa=None) is None


def test_valor_aberto_de_outra_estrategia_nao_entra():
    """O WFA aberto na outra aba pode ser de uma estratégia que não está na
    lista filtrada — aí não há o que herdar."""
    assert CC._valor_do_seletor(atual=None, ids={3, 8}, aberto_no_wfa=99) is None


def test_valor_sem_escolha_nem_aberto_usa_o_padrao():
    """Para o seletor de estratégia: sem escolha e sem a da outra aba na
    lista, cai na primeira que tem walk-forward — nunca numa lista vazia."""
    assert CC._valor_do_seletor(atual=None, ids={"a", "b"}, aberto_no_wfa="x",
                                padrao="a") == "a"


# --------------------------------------------------- I2: `_gates_e_leitura`


def _trades_completos(n=150, semente=11, contratos=1):
    """Trades sintéticos que passam pela `leitura_robustez` (>= 100 trades
    fora da amostra) sem precisar do banco real — mesmo padrão de
    `tests/test_candidata.py::_trades_rapidos`."""
    rng = np.random.default_rng(semente)
    dias = np.busday_offset(np.datetime64("2024-01-02"), np.arange(n))
    liquido = rng.normal(12.0, 8.0, n)
    return [
        {"exit_ts": str(d) + "T15:00:00", "liquido": float(v),
         "contratos": contratos}
        for d, v in zip(dias, liquido)
    ]


def _grade_plato_limpa(fr=(5,) * 9, deploy_idx=4):
    """Espaço/trials/deploy de um único parâmetro varrido, sem abstenção —
    o que interessa aqui é a MONTAGEM da lista de portões, não o platô."""
    valores = list(range(40, 40 + len(fr)))
    trials = [{"params": {"p": v}, "lucro": f * 100.0, "dd": 100.0}
              for v, f in zip(valores, fr)]
    return trials, {"p": valores}, {"p": float(valores[deploy_idx])}


NOMES_LENTOS = ["Ganha de entradas sorteadas ao acaso?",
               "Aguenta o desconto por muitas tentativas?",
               "Reotimizar compensou?"]


def _detalhes_wfa():
    trials, espaco, deploy_params = _grade_plato_limpa()
    d = {"capital": 10_000.0, "run_id": 1, "symbol": "WIN$N",
         "deploy": {"params": deploy_params}, "passos": None}
    return d, trials, espaco


def _injeta_banco_falso(monkeypatch, trials, espaco):
    """Troca tudo que `_gates_e_leitura` leria do banco real por dados
    falsos — nenhum destes testes abre o banco de verdade."""
    monkeypatch.setattr(CC.wfa_store, "trades",
                        lambda wfa_id: _trades_completos())
    monkeypatch.setattr(CC.optimizer, "detalhes_salva",
                        lambda run_id: {"espaco": espaco, "holdout_de": None})
    monkeypatch.setattr(CC.optimizer, "carregar_salva", lambda run_id: trials)
    monkeypatch.setattr(CC.db, "load_instrument_yaml",
                        lambda symbol: {"tick_value": 1.0})


def test_gates_e_leitura_monta_os_12_portoes_pendentes_antes_de_rodar(monkeypatch):
    """I2: sem este teste, `_gates_e_leitura` podia devolver só os nove
    portões rápidos e a tela mostraria "aprovada 9/9" — verde — sem nunca
    ter rodado os três testes demorados (aleatório, tentativas, reotimizar
    compensou). Antes de rodar, são 12 no total e os três últimos ficam
    pendentes, sem resultado."""
    d, trials, espaco = _detalhes_wfa()
    _injeta_banco_falso(monkeypatch, trials, espaco)
    monkeypatch.setattr(CC.TESTES, "resultado_de", lambda wfa_id: None)

    leitura, gates, de, ate = CC._gates_e_leitura(7, d)
    assert not leitura.get("erro")
    assert len(gates) == 12
    lentos = gates[-3:]
    assert [g["nome"] for g in lentos] == NOMES_LENTOS
    assert all(g["ok"] is None and g["valor"] == "aguardando" for g in lentos)


def test_gates_e_leitura_preenche_os_tres_lentos_quando_ja_rodaram(monkeypatch):
    """Mesmo cenário, mas com `TESTES.resultado_de` já publicado — os três
    últimos portões precisam vir com o resultado de verdade, não mais
    "aguardando"."""
    d, trials, espaco = _detalhes_wfa()
    _injeta_banco_falso(monkeypatch, trials, espaco)
    prontos = [
        candidata.portao_aleatorio({"p": 0.01, "calibracao_ok": True}),
        candidata.portao_tentativas({"p": 0.02}),
        candidata.alerta_reotimizar(70.0),
    ]
    monkeypatch.setattr(CC.TESTES, "resultado_de",
                        lambda wfa_id: {"portoes": prontos})

    _, gates, _, _ = CC._gates_e_leitura(7, d)
    assert len(gates) == 12
    assert gates[-3:] == prontos
    assert all(g["ok"] is not None for g in gates[-3:])
    assert [g["nome"] for g in gates[-3:]] == NOMES_LENTOS


# ------------------------------- nomes de tela (bug relatado pelo operador)


def test_resumo_mostra_o_nome_da_inteligencia_nao_a_chave():
    """O banco guarda `ulcer` e `vizinhanca`; quem escolheu na aba
    Walk-Forward escolheu "Estabilidade de Drawdown" e "Platô Pessimista".
    Mostrar a chave faz parecer outra inteligência."""
    d = {"strategy": "rompimento_canal", "symbol": "WIN$N", "is_meses": 12,
         "oos_meses": 6, "inteligencia": "ulcer", "holdout": False}
    texto = CC._texto_resumo(d)
    assert "Estabilidade de Drawdown" in texto and "ulcer" not in texto
    assert "Platô Pessimista" in CC._nome_da_inteligencia("vizinhanca")


def test_resumo_mostra_o_nome_da_estrategia_nao_o_do_arquivo():
    """`rompimento_canal` é o arquivo; a tela mostra o nome declarado pela
    estratégia, o mesmo das outras abas."""
    d = {"strategy": "rompimento_canal", "symbol": "WIN$N", "is_meses": 12,
         "oos_meses": 6, "inteligencia": "sharpe", "holdout": False}
    assert "rompimento_canal" not in CC._texto_resumo(d)
    # estratégia que não existe mais no disco continua aparecendo pelo módulo
    assert CC._nome_da_estrategia("nao_existe") == "nao_existe"
    assert CC._nome_da_estrategia(None) == "—"


# ------------------------------------------------ dimensionar (bloco 5)
def _trades(n=200, liquido=-50.0, dia_inicial=2):
    """Operações com saída em pregões seguidos, uma por dia."""
    return [{"n": i, "exit_ts": datetime(2024, 1, 1) + timedelta(days=i),
             "liquido": liquido if i % 4 else 120.0, "custo": 1.0}
            for i in range(n)]


def _wfa(perfil=None, capital=100_000.0):
    return {"symbol": "WIN$N", "capital": capital,
            "profile": perfil if perfil is not None else {
                "contratos": 1, "stop_tipo": "pontos", "stop_pontos": 300,
                "max_trades_dia": 2}}


def test_dimensionar_entrega_as_tres_partes(monkeypatch):
    """A função existe para ser testada sem montar o app Dash: junta trades,
    perfil e instrumento e devolve referência, contratos e disjuntor."""
    monkeypatch.setattr(CC.db, "load_instrument_yaml",
                        lambda s: {"point_value": 0.20, "tick_value": 1.0})
    leitura = {"boot": {"dd_p95": 900.0, "dd_p50": 300.0, "quedas":
                        np.linspace(0, 2000, 1001), "perdas_seguidas_p95": 8.0,
                        "submerso_p95": 30.0, "horizonte": 126,
                        "envelope_p10": np.linspace(-10, -200, 126)},
               "boot_12m": {}}
    ref, dim, disj = CC._dimensionar(_trades(), _wfa(), leitura, None, None,
                                     1.0, None, 50.0)
    assert ref["valor"] is not None and ref["de_onde"]
    assert dim["n"] >= 1 and dim["risco_efetivo_pct"] <= 1.0
    assert disj["nivel2"]["queda"] > disj["nivel1"]["queda"]


def test_dimensionar_com_perfil_sem_contratos_nao_divide_por_zero(monkeypatch):
    """Registro antigo, sem `contratos` no perfil: a curva vale 1 contrato,
    não zero."""
    monkeypatch.setattr(CC.db, "load_instrument_yaml",
                        lambda s: {"point_value": 0.20, "tick_value": 1.0})
    leitura = {"boot": {}, "boot_12m": {}}
    ref, dim, _ = CC._dimensionar(_trades(), _wfa(perfil={}), leitura,
                                  None, None, 1.0, None, 50.0)
    assert ref["valor"] is not None and dim["n"] >= 1


def test_dimensionar_sem_capital_nao_inventa_contratos(monkeypatch):
    monkeypatch.setattr(CC.db, "load_instrument_yaml",
                        lambda s: {"point_value": 0.20, "tick_value": 1.0})
    _, dim, disj = CC._dimensionar(_trades(), _wfa(capital=None),
                                   {"boot": {}, "boot_12m": {}},
                                   None, None, 1.0, None, 50.0)
    assert dim["n"] == 0 and dim["motivo"]
    assert disj["nivel2"]["queda"] is None


def test_dimensionar_sem_valor_do_ponto_ainda_mede_a_cauda(monkeypatch):
    """Instrumento sem `point_value` no YAML: o dia ruim de execução não é
    medido, e a conta segue com a média dos dias ruins."""
    monkeypatch.setattr(CC.db, "load_instrument_yaml", lambda s: {})
    ref, dim, _ = CC._dimensionar(_trades(), _wfa(), {"boot": {}, "boot_12m": {}},
                                  None, None, 1.0, None, 50.0)
    assert ref["dia_ruim"] is None
    assert ref["de_onde"] == "a média dos 5% piores pregões"


def test_pregao_movimentado_conta_so_dentro_da_janela(monkeypatch):
    """O dia mais movimentado alimenta o "dia ruim de execução" quando o
    perfil não tem limite diário. Ele precisa sair do MESMO recorte que
    produziu o resto da conta: um pregão cheio fora da janela do walk-forward
    inflaria a perda de referência e derrubaria os contratos sem motivo."""
    monkeypatch.setattr(CC.db, "load_instrument_yaml",
                        lambda s: {"point_value": 0.20, "tick_value": 1.0})
    # dentro da janela: no máximo 1 operação por pregão
    trades = _trades(n=120)
    # fora dela (antes do começo): um pregão com 8 operações
    fora = [{"n": 900 + i, "exit_ts": datetime(2023, 6, 1, 10 + i),
             "liquido": -30.0, "custo": 1.0} for i in range(8)]
    perfil = {"contratos": 1, "stop_tipo": "pontos", "stop_pontos": 300,
              "max_trades_dia": 0}          # sem limite: usa o observado
    leitura = {"boot": {}, "boot_12m": {}}
    ref, *_ = CC._dimensionar(fora + trades, _wfa(perfil=perfil), leitura,
                              "2024-01-01", "2024-06-01", 1.0, None, 50.0)
    # 1 operação no dia → stop dobrado = 300 × 0,20 × 2 = 120, mais o custo
    assert ref["dia_ruim"] == pytest.approx(121.0)


def test_leitura_do_wfa_e_calculada_uma_vez_so(monkeypatch):
    """Cada mexida no dial de risco não pode refazer os 2.000 caminhos
    sorteados: a curva não mudou, só o tamanho da posição."""
    chamadas = []

    def falsos(wid):
        chamadas.append(wid)
        return _trades(n=150)

    monkeypatch.setattr(CC.wfa_store, "trades", falsos)
    monkeypatch.setattr(CC.candidata, "leitura_robustez",
                        lambda *a, **k: {"boot": {}, "boot_12m": {}})
    CC._LEITURAS.clear()
    d = {"capital": 100_000.0, "passos": [], "oos_meses": 6}
    primeira = CC.leitura_do_wfa(77, d)
    segunda = CC.leitura_do_wfa(77, d)
    assert chamadas == [77]
    assert primeira is segunda
    CC._LEITURAS.clear()
