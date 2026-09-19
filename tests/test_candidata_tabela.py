"""A tela Candidata mostra os números numa tabela com mapa de calor.

A cor de cada valor sai da faixa boa/ruim que o próprio (?) descreve —
estes testes travam que a cor e o texto contam a mesma história.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.components import candidata_panel as CP  # noqa: E402
from ui.components import stats_cards as SC  # noqa: E402

CAP = 10_000.0


def _resumo(**troca):
    m = {"trades": 510, "lucro_liquido": 5474.0, "lucro_bruto": 5984.0,
         "custo_total": 510.0, "max_drawdown": 791.0, "max_drawdown_pct": 6.3,
         "max_drawdown_pct_capital": 7.9, "max_drawdown_rel_pct": 6.3,
         "profit_factor": 1.44, "win_rate": 23.3, "payoff": 4.73,
         "expectativa": 10.73, "fator_recuperacao": 6.92, "sharpe": 1.27,
         "sortino": 3.74, "trades_por_dia": 1.49}
    m.update(troca)
    return m


def _leitura(resumo=None, dd=831.0, seguidas=15.0, topo=125.0, topo50=57.0,
             ordem=1395.0):
    boot = {"horizonte": 131, "bloco": 1, "dd_p95": dd,
            "perdas_seguidas_p95": seguidas, "submerso_p95": topo,
            "submerso_p50": topo50}
    return {"resumo": resumo or _resumo(), "boot": boot, "boot_12m": {},
            "ordenacao": {"dd_p95": ordem}, "pregoes": 1044,
            "perdas_seguidas_reais": 11}


def _por_nome(grupos):
    return {l["nome"]: l for _, _, linhas in grupos for l in linhas}


# -------------------------------------------------- a fonte única dos textos
def test_itens_e_cartoes_saem_da_mesma_fonte():
    """Os cartões das abas Backtest e Walk-Forward e a tabela da Candidata
    usam os mesmos números e as mesmas explicações."""
    m = _resumo(periodo="01/03/2022 → 01/03/2026")
    itens = SC.itens(m)
    assert [i["rotulo"] for i in itens] == list(SC.cartoes(m))
    assert all(i["explica"] for i in itens)


# ------------------------------------------------------------------ tabela
def test_tabela_tem_os_dois_grupos_e_todos_os_numeros():
    grupos = CP.linhas(_leitura(), CAP)
    assert [g[0] for g in grupos] == ["Resultado fora da amostra",
                                      "Quanto a estratégia aguenta"]
    nomes = _por_nome(grupos)
    for n in ("lucro líquido", "max drawdown", "perda esperada · 6 meses",
              "dias perdendo seguidos", "dias até novo topo",
              "perda com outra ordem"):
        assert n in nomes, n
    assert all(l["explica"] for l in nomes.values())


def test_cor_segue_a_faixa_do_capital():
    """Perda esperada: até 10% do capital é bom, acima de 20% é ruim."""
    assert _por_nome(CP.linhas(_leitura(dd=831.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "bom"
    assert _por_nome(CP.linhas(_leitura(dd=1500.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "medio"
    assert _por_nome(CP.linhas(_leitura(dd=2500.0), CAP))[
        "perda esperada · 6 meses"]["tom"] == "ruim"


def test_poucos_trades_fica_vermelho():
    """Abaixo de ~100 trades quase nada é conclusivo — é o que o (?) diz."""
    linhas = _por_nome(CP.linhas(_leitura(_resumo(trades=80)), CAP))
    assert linhas["trades"]["tom"] == "ruim"


def test_numero_sem_faixa_fica_sem_cor():
    """Win rate sozinho não diz nada: sem faixa, sem cor."""
    assert _por_nome(CP.linhas(_leitura(), CAP))["win rate"]["tom"] is None


def test_dias_ate_novo_topo_mostra_o_tipico_e_o_pior_na_nota():
    linha = _por_nome(CP.linhas(_leitura(topo=125.0, topo50=57.0), CAP))[
        "dias até novo topo"]
    assert linha["valor"] == "57"
    assert "125" in linha["nota"]


def test_lucro_negativo_fica_vermelho():
    linhas = _por_nome(CP.linhas(_leitura(_resumo(lucro_liquido=-300.0,
                                                  expectativa=-0.6)), CAP))
    assert linhas["lucro líquido"]["tom"] == "ruim"
    assert linhas["expectativa"]["tom"] == "ruim"


# ------------------------------------------ tarefa 7: linha "holdout"


def test_sem_holdout_gate_mostra_texto_fixo_sem_cor():
    linha = _por_nome(CP.linhas(_leitura(), CAP))["holdout"]
    assert linha["valor"] == "sem holdout nesta curva"
    assert linha["tom"] is None


def test_holdout_gate_sem_pregoes_tambem_conta_como_sem_holdout():
    """O portão do holdout roda mesmo sem holdout marcado (corte no futuro
    distante — ver `candidata.portoes_rapidos`) e devolve
    `pregoes_holdout=0`: a linha não pode ler isso como "R$ 0/mês"."""
    gate = {"pregoes_holdout": 0, "lucro_mes_holdout": None,
            "lucro_mes_antes": None}
    linha = _por_nome(CP.linhas(_leitura(), CAP, holdout_gate=gate))["holdout"]
    assert linha["valor"] == "sem holdout nesta curva"


def test_holdout_gate_com_numeros_formata_os_dois_em_reais_sem_cor():
    gate = {"pregoes_holdout": 42, "lucro_mes_holdout": 850.0,
            "lucro_mes_antes": 620.0}
    linha = _por_nome(CP.linhas(_leitura(), CAP, holdout_gate=gate))["holdout"]
    assert "850" in linha["valor"] and "no holdout" in linha["valor"]
    assert "620" in linha["nota"] and "antes do corte" in linha["nota"]
    assert linha["tom"] is None


# ------------------------------------------ tarefa 7: barra dos testes


def test_estado_testes_erro_tem_prioridade_sobre_rodando():
    est = CP.estado_testes({"rodando": False, "erro": "deu ruim",
                            "resultado": None})
    assert est["fase"] == "erro" and est["txt"] == "deu ruim"
    assert est["ocupado"] is False


def test_estado_testes_rodando_mostra_a_fase_e_o_percentual():
    est = CP.estado_testes({"rodando": True, "fase": "sorteando entradas",
                            "pct": 63, "erro": None})
    assert est["fase"] == "rodando" and est["txt"] == "sorteando entradas"
    assert est["pct"] == 63 and est["ocupado"] is True


def test_estado_testes_pronto_quando_ha_resultado_e_nao_esta_rodando():
    est = CP.estado_testes({"rodando": False, "erro": None,
                            "resultado": {"portoes": []}})
    assert est["fase"] == "pronto" and est["ocupado"] is False


def test_estado_testes_ocioso_por_padrao():
    est = CP.estado_testes({"rodando": False, "erro": None, "resultado": None})
    assert est["fase"] == "ocioso"


def test_estado_testes_de_outro_wfa_fica_ocioso_mesmo_pronto():
    """`TESTES` é um singleton só: os testes prontos do #8 não podem
    aparecer como "testes completos" enquanto a tela mostra o #3 — cada
    walk-forward tem seu próprio "aguardando" até rodar de novo."""
    e = {"rodando": False, "erro": None, "resultado": {"portoes": []},
         "wfa_id": 8}
    assert CP.estado_testes(e, wfa_id=3)["fase"] == "ocioso"
    assert CP.estado_testes(e, wfa_id=None)["fase"] == "ocioso"
    assert CP.estado_testes(e, wfa_id=8)["fase"] == "pronto"
    assert CP.estado_testes(e, wfa_id="8")["fase"] == "pronto"   # tipos batem


def test_estado_testes_rodando_de_outro_wfa_tambem_fica_ocioso():
    e = {"rodando": True, "fase": "sorteando entradas", "pct": 40,
         "erro": None, "wfa_id": 8}
    assert CP.estado_testes(e, wfa_id=3)["fase"] == "ocioso"
    assert CP.estado_testes(e, wfa_id=8)["fase"] == "rodando"


def test_estado_testes_sem_wfa_id_no_estado_nao_filtra():
    """Antes do primeiro `iniciar()`, `TESTES.estado` não tem `wfa_id` —
    nada a comparar, comportamento de sempre."""
    e = {"rodando": False, "erro": None, "resultado": None}
    assert CP.estado_testes(e, wfa_id=8)["fase"] == "ocioso"


# ------------------------------------- tarefa 7, rodada 1: o relógio próprio


def test_relogio_liga_enquanto_roda():
    assert CP.relogio_ligado({"rodando": True, "geracao": 1}, None) is True


def test_relogio_desliga_quando_nunca_rodou_nada():
    e = {"rodando": False, "resultado": None, "erro": None, "geracao": 0}
    assert CP.relogio_ligado(e, None) is False
    assert CP.relogio_ligado(e, {"g": 0}) is False


def test_relogio_fica_ligado_ate_o_store_alcancar_a_geracao():
    e = {"rodando": False, "resultado": {"portoes": []}, "erro": None,
         "geracao": 3}
    assert CP.relogio_ligado(e, None) is True
    assert CP.relogio_ligado(e, {"g": 2}) is True          # geração velha
    assert CP.relogio_ligado(e, {"g": 3}) is False          # alcançou


def test_relogio_fica_ligado_com_erro_tambem():
    e = {"rodando": False, "resultado": None, "erro": "deu ruim",
         "geracao": 1}
    assert CP.relogio_ligado(e, None) is True
    assert CP.relogio_ligado(e, {"g": 1}) is False


def test_relogio_prova_a_ordem_que_travava_o_selo():
    """A ordem exata do bug da rodada de correção 1: `cand_fim_dos_testes`
    lê "rodando" (não anuncia nada), a thread termina, e só DEPOIS
    `cand_botao_testes` lê o estado. Antes da correção, o botão via
    `rodando=False` e desligava o relógio direto (`not e["rodando"]`) sem
    o Store nunca ter recebido a geração — travando o selo em "aguardando"
    para sempre. Com `relogio_ligado`, o relógio continua ligado até o
    Store alcançar."""
    estado = {"rodando": True, "resultado": None, "erro": None,
             "geracao": 5, "wfa_id": 8}
    store = None

    # 1) cand_fim_dos_testes roda enquanto ainda está "rodando": não anuncia
    pronto = estado.get("resultado") is not None or estado.get("erro")
    anuncia_agora = not estado["rodando"] and pronto and \
        (store or {}).get("g") != estado.get("geracao")
    assert anuncia_agora is False           # ainda rodando, nada a anunciar

    # 2) a thread termina ENTRE as duas leituras
    estado = {**estado, "rodando": False, "resultado": {"portoes": []}}

    # 3) cand_botao_testes lê o estado agora — a régua antiga (`not
    #    e["rodando"]`) desligaria o relógio aqui; a nova mantém ligado
    #    porque o Store (`store`) ainda não tem a geração 5
    assert CP.relogio_ligado(estado, store) is True

    # 4) só na próxima batida, depois de `cand_fim_dos_testes` finalmente
    #    anunciar (agora que "rodando" já é False), o relógio pode desligar
    store = {"g": estado["geracao"]}
    assert CP.relogio_ligado(estado, store) is False


# ---------------------------------------- bloco 5: tamanho e desligamento
def _dim(**troca):
    d = {"n": 3, "por_risco": 3, "por_margem": None, "por_folga": None,
         "limite": "risco", "risco_pedido_pct": 1.0, "risco_efetivo_pct": 0.9,
         "perda_ref": 300.0, "margem": None, "uso_margem_pct": 50.0,
         "motivo": None}
    d.update(troca)
    return d


def _ref(**troca):
    r = {"valor": 300.0, "de_onde": "a média dos 5% piores pregões",
         "cvar": -300.0, "quantos": 53, "fracao": 0.051, "pior_dia": -128.0,
         "dia_ruim": 240.0, "motivo": None}
    r.update(troca)
    return r


def _disj(**troca):
    d = {"nivel1": {"queda": 1200.0, "perdas_seguidas": 15,
                    "lucro_no_prazo": -200.0, "faixa_por_pregao": [-10.0],
                    "alarme_pct": 20.0, "acao": "reduzir para 1 contrato"},
         "nivel2": {"queda": 1800.0, "pct": 18.0, "alarme_pct": 5.0,
                    "risco_de_desligar_pct": 5.0,
                    "acao": "desligar e reotimizar"},
         "recorte": "curva inteira", "dias_sem_topo": 125,
         "limite_dia_reais": None, "limite_dia_trades": None,
         "horizonte": 131, "motivo": None}
    d.update(troca)
    return d


def _nomes(grupos):
    return [l["nome"] for _, _, linhas in grupos for l in linhas]


def test_bloco_de_tamanho_tem_os_dois_grupos_e_os_numeros():
    grupos = CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP)
    assert [g[0] for g in grupos] == ["Quanto operar", "Quando parar"]
    nomes = _nomes(grupos)
    for esperado in ("contratos", "risco por pregão", "perda de referência",
                     "reduzir para 1 contrato", "desligar e reotimizar",
                     "dias perdendo seguidos", "dias sem novo topo"):
        assert esperado in nomes, esperado


def test_contratos_zero_fica_vermelho_e_mostra_o_motivo():
    """Reprovação por capital insuficiente é resposta, não erro — e precisa
    dizer qual conta zerou, senão o usuário mexe no dial errado."""
    dim = _dim(n=0, risco_efetivo_pct=None,
               motivo="o capital não comporta nem 1 contrato: 1 contrato já "
                      "arrisca mais do que o limite pedido")
    linha = next(l for _, _, ls in CP.linhas_tamanho(dim, _ref(), _disj(), CAP)
                 for l in ls if l["nome"] == "contratos")
    assert linha["valor"] == "0" and linha["tom"] == "ruim"
    assert "arrisca mais" in linha["nota"]


def test_risco_efetivo_aparece_junto_do_pedido():
    """Entre 1 e 2 contratos o risco dobra: mostrar só o pedido seria
    mentira confortável."""
    linha = next(l for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP)
                 for l in ls if l["nome"] == "risco por pregão")
    assert "0,9" in linha["valor"] and "1,0" in linha["nota"]


def test_perda_de_referencia_diz_de_onde_veio_e_mostra_as_tres_leituras():
    grupos = CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP)
    linha = next(l for _, _, ls in grupos for l in ls
                 if l["nome"] == "perda de referência")
    assert "5% piores" in linha["nota"]
    nomes = _nomes(grupos)
    assert "pior pregão já ocorrido" in nomes


def test_garantia_nao_informada_nao_vira_zero_na_tela():
    """Margem em branco é dado que falta, não garantia de graça."""
    linha = next(l for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP)
                 for l in ls if l["nome"] == "garantia por contrato")
    assert "não informada" in linha["valor"] and linha["tom"] is None


def test_alarme_falso_alto_no_desligar_fica_vermelho():
    """Desligar uma estratégia viva em 1 de cada 4 ciclos é disjuntor que
    dispara sozinho."""
    disj = _disj(nivel2={**_disj()["nivel2"], "risco_de_desligar_pct": 25.0})
    linha = next(l for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), disj, CAP)
                 for l in ls if l["nome"] == "desligar e reotimizar")
    assert linha["tom"] == "ruim"


def test_sem_disjuntor_a_tabela_diz_nao_medido_e_nao_zero():
    disj = _disj(nivel1={**_disj()["nivel1"], "queda": None},
                 nivel2={**_disj()["nivel2"], "queda": None, "pct": None,
                         "risco_de_desligar_pct": None},
                 motivo="sem número de contratos não há limite")
    linhas = [l for _, _, ls in CP.linhas_tamanho(_dim(n=0), _ref(), disj, CAP)
              for l in ls if l["nome"] in ("reduzir para 1 contrato",
                                           "desligar e reotimizar")]
    assert all(l["valor"] == "não medido" for l in linhas)


def test_perda_de_referencia_nao_medida_nao_inventa_numero():
    ref = _ref(valor=None, de_onde=None, cvar=None,
               motivo="a curva não tem pregão nenhum")
    linha = next(l for _, _, ls in CP.linhas_tamanho(_dim(n=0), ref, _disj(), CAP)
                 for l in ls if l["nome"] == "perda de referência")
    assert linha["valor"] == "não medido"
    assert "pregão nenhum" in linha["nota"]


def test_todo_numero_tem_explicacao():
    """Regra da tela: nenhum número sem (?) dizendo o que é e qual a faixa."""
    for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP):
        for l in ls:
            assert l["explica"] and len(l["explica"]) > 40, l["nome"]


# as quatro linhas que escalam com o número de contratos: as duas do
# disjuntor mais o pior lucro do prazo e o limite do dia, que também são
# multiplicados por ele dentro de `tamanho.disjuntor`
ESCALAM = ("reduzir para 1 contrato", "desligar e reotimizar",
           "pior lucro esperado no prazo", "limite do dia")


def test_com_zero_contratos_o_disjuntor_aparece_com_o_aviso():
    """Vazio ali seria esconder número medido de quem mais precisa dele: a
    tela mostra a conta de 1 contrato, avisando. E o aviso precisa estar em
    TODA linha multiplicada pelos contratos — ler "seu limite do dia é R$
    300" sem aviso é ler um número que não é o seu."""
    disj = _disj(limite_dia_reais=300.0, limite_dia_trades=3)
    linhas = [l for _, _, ls in CP.linhas_tamanho(_dim(n=0), _ref(), disj, CAP)
              for l in ls if l["nome"] in ESCALAM]
    assert len(linhas) == 4
    assert all(l["valor"] != "não medido" for l in linhas)
    assert all(l["nota"].startswith("conta feita com 1 contrato")
               for l in linhas), [l["nome"] for l in linhas]


def test_o_aviso_cita_a_conta_que_realmente_zerou():
    """Quando quem travou foi a garantia, mandar o usuário mexer no risco é
    o mesmo defeito que o motivo da linha "contratos" existe para evitar."""
    por_margem = _dim(n=0, limite="margem", por_margem=0,
                      margem=60_000.0, risco_efetivo_pct=None)
    linha = next(l for _, _, ls in CP.linhas_tamanho(por_margem, _ref(),
                                                     _disj(), CAP)
                 for l in ls if l["nome"] == "desligar e reotimizar")
    assert "garantia" in linha["nota"] and "risco por pregão" not in linha["nota"]

    por_risco = _dim(n=0, limite="risco", risco_efetivo_pct=None)
    linha = next(l for _, _, ls in CP.linhas_tamanho(por_risco, _ref(),
                                                     _disj(), CAP)
                 for l in ls if l["nome"] == "desligar e reotimizar")
    assert "risco por pregão" in linha["nota"]


def test_com_contratos_de_verdade_nao_aparece_aviso_nenhum():
    linhas = [l for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP)
              for l in ls if l["nome"] == "desligar e reotimizar"]
    assert "mais do que o seu risco" not in linhas[0]["nota"]


def test_todo_numero_diz_o_que_e_bom_e_o_que_e_ruim():
    """Regra da tela, e não só "ter um (?)": sem a faixa, o número fica sem
    régua e o operador não sabe se aquilo é bom."""
    for _, _, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP):
        for l in ls:
            texto = l["explica"].lower()
            assert "bom:" in texto or "ruim:" in texto, l["nome"]


def test_explicacoes_sem_jargao():
    """O usuário pediu linguagem simples. Estas palavras exigem conhecimento
    prévio e já apareceram na tela: cauda, ciclos, caminhos simulados."""
    proibidas = ("cauda", "dos ciclos", "caminhos simulados", "percentil",
                 "cvar", "drawdown", "bootstrap")
    for _, explica, ls in CP.linhas_tamanho(_dim(), _ref(), _disj(), CAP):
        # a NOTA conta tanto quanto o (?): ela é a primeira coisa lida
        textos = ([explica] + [l["explica"] for l in ls]
                  + [l["nota"] for l in ls])
        for t in textos:
            for palavra in proibidas:
                assert palavra not in t.lower(), (palavra, t[:60])
