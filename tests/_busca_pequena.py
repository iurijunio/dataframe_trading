"""Uma busca real e pequena (WIN, 1º semestre de 2024) feita no próprio
processo do teste, para projeção, grupos e detalhe terem o que ler."""
from core.busca import avaliador, banco, grupos, motor
from core.busca.espaco import Espaco
from core.engine.execution import ExecutionProfile


def config():
    esp = Espaco("adx_direcao", "WIN$N", fechamento="17:30",
                 faixas={"timeframe": {"ligados": ["M5", "M15"]},
                         "di_periodo": {"de": 8, "ate": 16},
                         "adx_suavizacao": {"de": 8, "ate": 14},
                         "amplitude_max": {"de": 300, "ate": 900, "passo": 300}})
    return {"simbolo": "WIN$N", "estrategia": "adx_direcao", "espaco": esp.para_json(),
            "perfil_base": ExecutionProfile(corretagem_por_contrato=0.5,
                                            fechamento="17:30").to_config(),
            "de": "2024-01-01", "ate": "2024-06-28T17:59:00",
            "wf_config": {"treino_meses": 2, "teste_meses": 1, "passo_meses": 1,
                          "holdout_meses": 1},
            "minimo": 40, "criterio": "fr", "semente": 5}


def rodar(lotes: int = 3) -> int:
    cfg = config()
    bid = banco.criar(cfg)
    motor.escrever_json(banco.pasta_da(bid) / "controle.json",
                        {"parar_as_ligado": False, "nucleos": 2})
    avaliador.iniciar_nucleo(cfg["simbolo"], cfg["de"], cfg["ate"], cfg["estrategia"])
    b = motor.Busca(bid)
    ctx = b._ctx()

    def local(grupos_, _config, _n):
        out = []
        for chave, tarefas in grupos_:
            out += avaliador.avaliar_grupo(chave, tarefas, ctx)
        return out

    b._avaliar_fora = local
    b.rodar(max_lotes=lotes)
    esp = Espaco.de_json(cfg["espaco"])
    gs = grupos.agrupar(banco.ler_elites(bid), banco.ler_combos(bid), esp)
    banco.gravar_grupos(bid, 1, gs)
    return bid
