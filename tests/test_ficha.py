"""Testes da ficha da vencedora e da barra de progresso do walk-forward.

A ficha tem uma promessa só: mostrar TUDO o que é preciso para operar a
combinação, para QUALQUER estratégia. Por isso os testes não olham um campo
por vez — percorrem o `ExecutionProfile` inteiro e inventam estratégias que
não existem.
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engine.execution import ExecutionProfile  # noqa: E402
from ui.components import catalogo as C  # noqa: E402
from ui.components import ficha as FI  # noqa: E402
from ui.components import wfa_panel as WP  # noqa: E402

CANAL = SimpleNamespace(
    label="Rompimento de canal",
    params_schema={"periodo_canal": {"label": "Período do canal", "default": 20},
                   "folga_ticks": {"label": "Folga do rompimento (ticks)",
                                   "default": 1}})


def _txt(**kw) -> str:
    base = dict(estrategia=CANAL, params={"periodo_canal": 79, "folga_ticks": 9},
                perfil={}, espaco={})
    base.update(kw)
    return str(FI.ficha(**base))


# ---------------------------------------------------------- completude
def test_todo_campo_do_motor_esta_catalogado():
    """Um campo novo no ExecutionProfile ainda aparece sem catálogo (em
    "outros"), mas com o nome cru. Este teste é o lembrete de dar rótulo."""
    faltando = [f.name for f in fields(ExecutionProfile) if f.name not in C.CAMPOS]
    assert faltando == []


def test_todo_campo_do_perfil_aparece_ou_esta_condicionado():
    """Percorre o perfil inteiro. Cada campo tem que estar na ficha, a menos
    que a própria condição dele o esconda (ATR do alvo com alvo em pontos)."""
    for modo in ("contratos_fixos", "risco_fixo"):
        for tipo in ("pontos", "atr"):
            perfil = {"modo_posicao": modo, "alvo_tipo": tipo, "stop_tipo": tipo,
                      "risco_por_trade": 200.0}
            t = _txt(perfil=perfil)
            efetivo = FI.perfil_efetivo(perfil, {})
            for nome, (grupo, rotulo, _fmt, *cond) in C.CAMPOS.items():
                visivel = not cond or efetivo[cond[0][0]] == cond[0][1]
                assert (f"'{rotulo}'" in t) == visivel, (nome, modo, tipo)


def test_timeframe_direcao_e_dias_com_o_texto_da_tela():
    t = _txt(perfil={"timeframe": "M5", "direcao": "compra",
                     "dias_semana": [1, 3, 5]})
    assert "'M5'" in t
    assert "'só compra'" in t
    assert "'seg · qua · sex'" in t
    assert "'seg a sex'" in _txt(perfil={"dias_semana": [1, 2, 3, 4, 5]})


def test_zero_que_desliga_aparece_como_desligado():
    t = _txt(perfil={"breakeven_pct": 0, "trailing_pontos": 0,
                     "limite_perda_contrato": 0, "step_gatilho_pct": 30})
    assert t.count("'desligado'") >= 3
    assert "'30% do alvo'" in t


def test_parametro_da_janela_vence_o_perfil_gravado():
    """A mineração gravou alvo 600; a janela escolheu 1.150. Opera-se 1.150."""
    t = _txt(perfil={"alvo_pontos": 600},
             params={"periodo_canal": 79, "alvo_pontos": 1150})
    assert "'1.150'" in t and "'600'" not in t


# ------------------------------------------------------------ dinâmica
def test_qualquer_estrategia_usa_os_rotulos_dela():
    medias = SimpleNamespace(params_schema={
        "media_rapida": {"label": "Média rápida", "default": 9},
        "media_lenta": {"label": "Média lenta", "default": 21}})
    t = str(FI.ficha(estrategia=medias, params={"media_rapida": 7},
                     perfil={}, espaco={}))
    assert "'Média rápida'" in t and "'Média lenta'" in t
    assert "'Período do canal'" not in t
    assert "'21'" in t                      # a lenta não veio: vale o padrão


def test_parametro_fora_do_schema_aparece_com_o_nome_cru():
    """Estratégia mudou depois da mineração: o parâmetro gravado não some."""
    t = _txt(params={"periodo_canal": 79, "filtro_antigo": 3})
    assert "'filtro_antigo'" in t


def test_campo_de_perfil_sem_catalogo_cai_em_outros(monkeypatch):
    monkeypatch.delitem(C.CAMPOS, "slippage_ticks")
    t = _txt(perfil={"slippage_ticks": 2})
    assert "'outros'" in t and "'slippage_ticks'" in t


def test_geral_entra_no_topo():
    t = _txt(geral={"ativo": "WIN$N", "mineração": "#40 · canal"})
    assert "'Geral'" in t and "'WIN$N'" in t and "'#40 · canal'" in t


# ----------------------------------------------------- faixa minerada
def test_valor_na_borda_da_faixa_acende_o_alerta():
    t = _txt(params={"periodo_canal": 80, "folga_ticks": 9},
             espaco={"periodo_canal": [40, 50, 60, 70, 80], "folga_ticks": [9]})
    assert "na borda de cima" in t
    assert "40 → 80 · passo 10" in t
    assert "fi-minerado" in t


def test_vizinho_da_borda_tambem_e_alerta():
    """O caso real da #40: periodo_canal = 79 numa faixa que parou em 80."""
    vals = list(range(40, 81))
    assert "perto da borda de cima" in _txt(espaco={"periodo_canal": vals})
    t = _txt(params={"periodo_canal": 60}, espaco={"periodo_canal": vals})
    assert "perto" not in t and "50% da faixa" in t


def test_meio_de_grade_curta_nao_e_borda():
    """Em 600/800/1000 o 800 está a um passo das duas bordas — e é o ótimo
    cercado de vizinhos testados, não um alerta."""
    t = _txt(params={"periodo_canal": 79, "alvo_pontos": 800},
             espaco={"alvo_pontos": [600, 800, 1000]})
    # a classe, e não a palavra: "borda" também está no texto do (?)
    assert "50% da faixa" in t
    assert "pp-borda" not in t and "pp-perto" not in t


def test_campo_de_execucao_minerado_tambem_ganha_faixa():
    t = _txt(params={"periodo_canal": 79, "stop_pontos": 150},
             espaco={"stop_pontos": [100, 150, 200, 250, 300]})
    assert "100 → 300 · passo 50" in t


def test_valores_inteiros_nao_mostram_ponto_zero():
    assert FI.valor(79.0) == "79"
    assert FI.valor(1150.0) == "1.150"
    assert FI.valor(0.25) == "0,25"
    assert FI.valor(None) == "—"


# ------------------------------------------------------ barra de progresso
def test_progresso_varrendo_mostra_contagem_e_tempo_restante():
    e = {"rodando": True, "feitos": 10, "total": 40, "inicio": 100.0, "agora": 104.0}
    est = WP.estado_progresso(e, 40, 400)
    assert est["fase"] == "varrendo" and est["ocupado"]
    assert est["pct"] == pytest.approx(25.0) and est["pct_txt"] == "25%"
    assert "falta ~12 s" in str(est["txt"])          # 4 s para 10 → 12 s para 30
    assert "25%" in est["veu"]


def test_progresso_antes_do_primeiro_resultado_diz_que_esta_iniciando():
    est = WP.estado_progresso({"rodando": True, "feitos": 0, "total": 41}, 40, 400)
    assert est["ocupado"] and "iniciando" in str(est["txt"])
    assert "41 combinações na fila" in str(est["txt"])


def test_progresso_montando_segura_o_botao_ate_a_tela_desenhar():
    e = {"rodando": False, "pronto": True, "entregue": False, "run_id": 40, "total": 41}
    est = WP.estado_progresso(e, 40, 400)
    assert est["fase"] == "montando" and est["ocupado"]


def test_progresso_pronto_resume_a_varredura():
    e = {"rodando": False, "pronto": True, "entregue": True, "run_id": 40,
         "total": 41, "uteis": 41, "segundos": 1.84, "mb": 0.91}
    est = WP.estado_progresso(e, 40, 400)
    assert est["fase"] == "pronto" and not est["ocupado"] and est["veu"] is None
    t = str(est["txt"])
    assert "41 combinações" in t and "1,8 s" in t and "0,9 MB" in t


def test_progresso_de_outra_mineracao_nao_mostra_resumo_velho():
    e = {"rodando": False, "pronto": True, "entregue": True, "run_id": 39,
         "total": 41, "uteis": 41}
    assert WP.estado_progresso(e, 40, 400)["txt"] == "pronto para executar"
    assert WP.estado_progresso({}, None, 400)["fase"] == "ocioso"


def test_progresso_acima_do_teto_vira_erro():
    e = {"rodando": False, "pronto": True, "entregue": True, "run_id": 40,
         "total": 900, "uteis": 900, "mb": 512.0, "mensagem": "acima do teto"}
    est = WP.estado_progresso(e, 40, 400)
    assert est["fase"] == "erro" and not est["ocupado"]
