"""A coluna de combinação mostra SÓ o que a varredura varreu.

O usuário minerava ATR e a tabela listava alvo_pontos, stop_pontos,
breakeven e todo o resto fixo — nada disso mudou de uma linha para a
outra. O `params` de cada linha continua COMPLETO (é ele que carrega a
combinação de volta para a tela, alimenta a Candidata e vai para o
banco); só o TEXTO de apresentação é filtrado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core.optimizer import (  # noqa: E402
    Mineracao, campos_minerados, carregar_salva, txt_combinacao,
)
from tests._cadeia import banco, mineracao  # noqa: E402,F401

# o exemplo real do usuário: varredura de ATR, tabela listando tudo
PARAMS = {
    "ema_curta": 3, "ema_longa": 50, "distancia_abertura": 500,
    "alvo_pontos": 650, "stop_pontos": 750, "breakeven_pct": 0,
    "step_gatilho_pct": 0, "step_distancia_pct": 0, "trailing_pontos": 0,
    "alvo_razao": 2, "alvo_atr_periodo": 78, "alvo_atr_mult": 5,
    "stop_atr_periodo": 6, "stop_atr_mult": 6,
}
# marcado: ema_curta (estratégia) e dois campos ATR; o resto é fixo
ESPACO = {"ema_curta": [2, 3, 4], "ema_longa": [50],
          "distancia_abertura": [500], "alvo_pontos": [650],
          "stop_pontos": [750], "breakeven_pct": [0], "step_gatilho_pct": [0],
          "step_distancia_pct": [0], "trailing_pontos": [0],
          "alvo_razao": [2], "alvo_atr_periodo": [48, 78],
          "alvo_atr_mult": [5], "stop_atr_periodo": [6],
          "stop_atr_mult": [4, 6]}
FIXOS = ("ema_longa", "alvo_pontos", "stop_pontos", "breakeven_pct",
         "alvo_razao", "stop_atr_periodo")


def test_coluna_mostra_so_o_que_a_varredura_varreu():
    varridos = campos_minerados(ESPACO)
    assert varridos == {"ema_curta", "alvo_atr_periodo", "stop_atr_mult"}

    txt = txt_combinacao(PARAMS, varridos)
    assert "ema_curta=3" in txt
    assert "alvo_atr_periodo=78" in txt
    assert "stop_atr_mult=6" in txt
    for fixo in FIXOS:
        assert f"{fixo}=" not in txt, fixo


def test_sem_nada_varrido_o_texto_completo_identifica_a_linha():
    """Varredura de uma combinação só: não há o que filtrar, e esconder
    tudo deixaria a coluna em branco numa tabela de uma linha."""
    assert txt_combinacao(PARAMS, None) == " · ".join(
        f"{k}={v}" for k, v in PARAMS.items())
    assert txt_combinacao(PARAMS, campos_minerados({})) == \
        " · ".join(f"{k}={v}" for k, v in PARAMS.items())


def test_ranking_da_tabela_aplica_o_filtro():
    row = {"params": dict(PARAMS), "trial_id": 1,
           "geral": {"lucro": 10.0, "trades": 5, "max_dd": 1.0,
                     "profit_factor": 1.1, "fator_recuperacao": 1.0},
           "folds": {"positivos": 1, "com_trades": 1, "mediana_lucro": 1.0},
           "consistencia": 1.0, "score": 1.0, "passa_filtro": True}
    m = Mineracao()
    m._contexto = {"espaco": ESPACO}          # a mesma fonte do _rodar
    linhas = m._ranking([row])

    txt = linhas[0]["params_txt"]
    assert "ema_curta=3" in txt and "alvo_atr_periodo=78" in txt
    assert "alvo_pontos=" not in txt and "stop_pontos=" not in txt
    # a linha guarda o params completo: clicar carrega tudo de volta
    assert linhas[0]["params"] == PARAMS


def test_mineracao_salva_reproduz_o_espaco_gravado(banco):
    mineracao(7)
    with db.connect_write() as con:
        con.execute("UPDATE mining_runs SET space = ? WHERE run_id = 7",
                    [json.dumps(ESPACO)])
        con.execute(
            "INSERT INTO mining_trials (run_id, trial_id, params, lucro) "
            "VALUES (7, 1, ?, 100.0)", [json.dumps(PARAMS)])

    linhas = carregar_salva(7)
    txt = linhas[0]["params_txt"]
    assert "ema_curta=3" in txt and "stop_atr_mult=6" in txt
    for fixo in FIXOS:
        assert f"{fixo}=" not in txt, fixo
    assert linhas[0]["params"] == PARAMS


def test_mineracao_salva_sem_espaco_gravado_mostra_o_texto_completo(banco):
    """runs gravadas antes da coluna `space` existir: sem o espaço não dá
    para saber o que foi varrido, e o texto completo é o fallback."""
    mineracao(8)
    with db.connect_write() as con:
        con.execute(
            "INSERT INTO mining_trials (run_id, trial_id, params, lucro) "
            "VALUES (8, 1, ?, 100.0)", [json.dumps(PARAMS)])

    linhas = carregar_salva(8)
    assert linhas[0]["params_txt"] == " · ".join(
        f"{k}={v}" for k, v in PARAMS.items())


def test_passos_do_wfa_tambem_mostram_so_o_varrido():
    from ui.components.wfa_panel import linhas_steps

    j = SimpleNamespace(deploy=False, step=1, is_de="2026-01-01",
                        is_ate="2026-06-30", oos_de="2026-07-01",
                        oos_ate="2026-12-31")
    p = SimpleNamespace(janela=j, params=dict(PARAMS),
                        is_={"lucro": 1.0}, oos={"lucro": 2.0, "trades": 10},
                        wfe_lucro=1.0, fora_do_mercado=False,
                        poucos_trades=False)

    txt = linhas_steps([p], ESPACO)[0]["params_txt"]
    assert "ema_curta=3" in txt
    assert "alvo_pontos=" not in txt and "alvo_razao=" not in txt
