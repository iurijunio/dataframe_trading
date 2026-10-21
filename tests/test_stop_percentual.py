"""Stop e alvo em porcentagem do preço de entrada (`stop_tipo`/`alvo_tipo` =
"percentual").

A distância sai do preço de entrada, e não de um número fixo de pontos:
0,50% com WIN a 210.000 são 1.050 pontos. Por isso o nível muda com o
preço, e o teste de distância usa um preço de entrada de verdade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import optimizer  # noqa: E402
from core.engine.execution import ExecutionProfile, _nivel_pct, backtest  # noqa: E402
from strategies.base import Signals, empty_like  # noqa: E402
from tests.test_engine import WIN  # noqa: E402
from tests.test_kernel_stop_vigente import _barras  # noqa: E402
from ui.components import catalogo as C  # noqa: E402
from ui.components import controls as CT  # noqa: E402
from ui.components import ficha as FI  # noqa: E402


def _perfil(**kw) -> ExecutionProfile:
    base = dict(entrada_inicio="09:00", entrada_fim="09:05", fechamento="09:05",
                slippage_ticks=0)
    base.update(kw)
    return ExecutionProfile(**base)


def _sinal(n, lado="long", barra=0):
    s = empty_like(n)
    s["entry_long" if lado == "long" else "entry_short"][barra] = True
    return Signals(**s)


# a barra 1 abre em 210.000: a entrada da compra sai nesse preço
SOBE_210K = [
    (210000, 210010, 209990, 210000),
    (210000, 211500, 210000, 211000),
    (211000, 211200, 210900, 211100),
    (211100, 211200, 211000, 211100),
]

# venda: a barra 1 abre em 210.000 e vai para baixo
CAI_210K = [
    (210000, 210010, 209990, 210000),
    (210000, 210000, 208400, 208500),
    (208500, 208600, 208300, 208400),
    (208400, 208500, 208300, 208400),
]


# ------------------------------------------------------------ distância
def test_meio_por_cento_de_210_mil_sao_1050_pontos_no_tick_5():
    """O exemplo da tela: 0,50% de 210.000 = 1.050, já múltiplo de 5."""
    d = _nivel_pct(np.array([210000]), 0.5, 5)
    assert d.tolist() == [1050]


def test_distancia_arredonda_para_longe_da_entrada_no_tick():
    """1.052,5 -> 1.053 ao inteiro -> 1.055 ao tick 5 (para cima, longe).
    Cortar para 1.050 deixaria o stop mais perto do que foi pedido."""
    d = _nivel_pct(np.array([210000]), 0.5012, 5)
    assert d.tolist() == [1055]


def test_pct_zero_e_sem_protecao():
    assert _nivel_pct(np.array([210000, 210000]), 0, 5).tolist() == [0, 0]


def test_stop_percentual_na_compra_sai_da_abertura_da_entrada():
    # stop 0,50% de 210.000 = 1.050 pontos abaixo da entrada (210.000)
    r = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                 _perfil(stop_tipo="percentual", stop_pct=0.5, alvo_pontos=5000),
                 WIN)
    assert r.n_trades == 1
    assert r.trades["entry_px"][0] == 210000
    assert r.trades["stop_fim"][0] == 210000 - 1050


def test_stop_percentual_na_venda_fica_acima_da_entrada():
    r = backtest(_barras(CAI_210K), _sinal(len(CAI_210K), lado="short"),
                 _perfil(stop_tipo="percentual", stop_pct=0.5, alvo_pontos=5000),
                 WIN)
    assert r.n_trades == 1
    assert r.trades["side"][0] == -1
    assert r.trades["entry_px"][0] == 210000
    assert r.trades["stop_fim"][0] == 210000 + 1050


def test_alvo_percentual_na_compra_e_na_venda():
    # alvo 1% de 210.000 = 2.100; stop em pontos fixos para isolar o alvo
    comp = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                    _perfil(alvo_tipo="percentual", alvo_pct=1.0,
                            stop_pontos=5000), WIN)
    assert comp.trades["alvo_fim"][0] == 210000 + 2100
    vend = backtest(_barras(CAI_210K), _sinal(len(CAI_210K), lado="short"),
                    _perfil(alvo_tipo="percentual", alvo_pct=1.0,
                            stop_pontos=5000), WIN)
    assert vend.trades["alvo_fim"][0] == 210000 - 2100


def test_stop_e_alvo_percentuais_juntos():
    r = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                 _perfil(stop_tipo="percentual", stop_pct=0.5,
                         alvo_tipo="percentual", alvo_pct=1.0), WIN)
    assert r.trades["stop_fim"][0] == 210000 - 1050
    assert r.trades["alvo_fim"][0] == 210000 + 2100


def test_stop_percentual_vale_com_breakeven():
    """Breakeven mexe no stop em % do alvo; com alvo percentual, o gatilho
    sai do mesmo alvo e o stop vai para a entrada."""
    r = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                 _perfil(stop_tipo="percentual", stop_pct=0.5,
                         alvo_tipo="percentual", alvo_pct=1.0,
                         breakeven_pct=50.0), WIN)
    assert r.trades["stop_fim"][0] == r.trades["entry_px"][0] == 210000


def test_stop_percentual_alimenta_o_risco_fixo_por_sl_at_entry():
    r = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                 _perfil(stop_tipo="percentual", stop_pct=0.5,
                         alvo_pontos=5000), WIN)
    assert r.sl_at_entry.tolist() == [1050]


def test_tipos_antigos_nao_mudam_com_os_campos_novos():
    """Equivalência: com stop em pontos, o stop_pct novo não entra no cálculo."""
    base = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                    _perfil(stop_pontos=300, alvo_pontos=600), WIN)
    com_campo = backtest(_barras(SOBE_210K), _sinal(len(SOBE_210K)),
                         _perfil(stop_pontos=300, alvo_pontos=600,
                                 stop_pct=3.0, alvo_pct=7.0), WIN)
    assert base.trades["stop_fim"].tolist() == com_campo.trades["stop_fim"].tolist()
    assert base.trades["alvo_fim"].tolist() == com_campo.trades["alvo_fim"].tolist()
    assert base.trades["points"].tolist() == com_campo.trades["points"].tolist()


def test_perfil_padrao_continua_em_pontos():
    p = ExecutionProfile()
    assert p.stop_tipo == "pontos" and p.alvo_tipo == "pontos"
    assert p.stop_pct == 0.5 and p.alvo_pct == 1.0


# ------------------------------------------------------- perfil gravado
def test_from_config_e_to_config_carregam_os_campos_novos():
    p = ExecutionProfile(stop_tipo="percentual", stop_pct=0.75,
                         alvo_tipo="percentual", alvo_pct=1.5)
    d = p.to_config()
    assert d["stop_pct"] == 0.75 and d["alvo_pct"] == 1.5
    volta = ExecutionProfile.from_config({"gestao": d})
    assert volta.stop_tipo == "percentual" and volta.stop_pct == 0.75
    assert volta.alvo_tipo == "percentual" and volta.alvo_pct == 1.5


# --------------------------------------------------------- catálogo/tela
def test_catalogo_oferece_porcentagem_nos_dois_tipos():
    assert ("porcentagem do preço", "percentual") in C.OPCOES["stop_tipo"]
    assert ("porcentagem do preço", "percentual") in C.OPCOES["alvo_tipo"]


def test_ficha_mostra_porcentagem_com_duas_casas():
    assert FI.formatar("stop_pct", "pct_preco", 0.5) == "0,50%"
    assert FI.formatar("alvo_pct", "pct_preco", 1.0) == "1,00%"


def test_ficha_so_mostra_os_campos_do_tipo_percentual():
    perfil = {"stop_tipo": "percentual", "alvo_tipo": "pontos"}
    efetivo = FI.perfil_efetivo(perfil, {})
    assert efetivo["stop_tipo"] == "percentual"
    assert C.CAMPOS["stop_pct"][3] == ("stop_tipo", "percentual")
    assert C.CAMPOS["alvo_pct"][3] == ("alvo_tipo", "percentual")


def _ids(componente, acc=None):
    acc = {} if acc is None else acc
    cid = getattr(componente, "id", None)
    if cid is not None:
        acc[cid if isinstance(cid, str) else repr(sorted(cid.items()))] = componente
    filhos = getattr(componente, "children", None)
    if isinstance(filhos, (list, tuple)):
        for f in filhos:
            _ids(f, acc)
    elif filhos is not None and hasattr(filhos, "id"):
        _ids(filhos, acc)
    return acc


def test_sidebar_tem_os_blocos_de_porcentagem_escondidos():
    ids = _ids(CT.execucao())
    for bloco in ("blk-alvo-pct", "blk-stop-pct"):
        assert bloco in ids, bloco
        assert ids[bloco].style == {"display": "none"}


def test_campos_percentuais_sao_mineraveis_como_os_outros():
    from core.wfa_runner import CAMPOS_EXECUCAO_NOMES
    from ui.callbacks import SCHEMA_EXECUCAO

    for nome in ("alvo_pct", "stop_pct"):
        assert nome in CAMPOS_EXECUCAO_NOMES
        assert nome in SCHEMA_EXECUCAO
        assert nome in CT.CAMPOS_EXECUCAO
        assert SCHEMA_EXECUCAO[nome]["step"] == 0.01
    assert "alvo_pct" in optimizer._SO_VALE_COM
    assert "stop_pct" in optimizer._SO_VALE_COM


def test_espaco_tira_o_percentual_quando_o_tipo_e_pontos():
    espaco = {"stop_pct": [0.25, 0.5, 0.75], "stop_pontos": [100, 200]}
    util = optimizer.espaco_util(espaco, {"stop_tipo": "pontos"})
    assert util["stop_pct"] == [0.25]
    assert util["stop_pontos"] == [100, 200]
    util = optimizer.espaco_util(espaco, {"stop_tipo": "percentual"})
    assert util["stop_pct"] == [0.25, 0.5, 0.75]
