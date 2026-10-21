"""Nenhum parâmetro de estratégia pode ter o mesmo nome de um campo do
perfil de execução (camada 4): os dois viram o MESMO id na barra lateral e
o mesmo campo no dicionário do plano — marcar "minerar" num acendia o outro
(bug do "ADX direção" com o filtro ADX, 21/10/2026)."""
from core.engine.execution import ExecutionProfile
from strategies import registry


def test_parametros_de_estrategia_nao_colidem_com_o_perfil():
    perfil = set(ExecutionProfile.__dataclass_fields__)
    for info in registry.descobrir():
        mod = registry.definir(info["modulo"])
        colide = set(mod.params_schema) & perfil
        assert not colide, f"{mod.name}: {sorted(colide)} já é campo do perfil"
