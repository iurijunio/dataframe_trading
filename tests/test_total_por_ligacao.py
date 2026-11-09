"""Total por variante na conta (coluna Total do painel em partes): o mesmo
recorte da coluna Demo/Real do comparativo — só fechadas, desde o plano em
vigor, líquidas dos custos do plano."""
from datetime import date

from core import papel_leitura as PL
from core.leitura import total as TOTAL  # onde total_por_ligacao procura os nomes


def test_total_por_ligacao_so_fechadas_do_plano_em_vigor(monkeypatch):
    dia = date(2026, 10, 21)
    monkeypatch.setattr(TOTAL, "_ligacoes",
                        lambda con, pid, d: [{"ligacao_id": 1, "variante_id": 5}])
    monkeypatch.setattr(TOTAL, "_pregao", lambda con, lig, d: (7, None, None, None))
    monkeypatch.setattr(TOTAL, "_plano_do_dia",
                        lambda con, vid, d, g: {"plano_id": 7, "vale_a_partir": None})
    monkeypatch.setattr(TOTAL, "_custo_por_contrato", lambda p: 1.0)
    ops = [
        {"ligacao_id": 1, "plano_id": 7, "situacao": "fechada",
         "resultado": 30.0, "contratos": 1, "pontos": 100},
        # aberta não entra no total
        {"ligacao_id": 1, "plano_id": 7, "situacao": "aberta",
         "resultado": 5.0, "contratos": 1, "pontos": 10},
        # de outro plano: fora do recorte
        {"ligacao_id": 1, "plano_id": 8, "situacao": "fechada",
         "resultado": 99.0, "contratos": 1, "pontos": 1},
    ]
    monkeypatch.setattr(TOTAL, "_pregoes_demo",
                        lambda con, pid, d, origem="demo": [(dia, (None, ops))])
    m = PL.total_por_ligacao(None, 1, dia, "real")
    # 30 − custo de 1 contrato (1,0) = 29
    assert m[1]["n"] == 1
    assert m[1]["total"] == 29.0
