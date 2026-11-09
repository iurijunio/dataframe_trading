"""Leitura: utilidades usadas por todas as partes."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .. import db_manager as db


# Pregão que produziu papel (e por isso entra na curva do plano). O pulado
# não operou; o interrompido operou até o código mudar.
_PREGOES_QUE_CONTAM = ("rodando", "conferido", "interrompido")

# Início do pregão para a régua da expectativa; o fim é o fechamento do
# perfil do plano — a hora em que a variante para de operar.
_ABERTURA = time(9, 0)

_INSTRUMENTOS: dict[str, dict] = {}


# ------------------------------------------------------------ utilidades
def _hoje(hoje: date | None) -> date:
    return hoje or date.today()


def _limites(dia: date) -> tuple[datetime, datetime]:
    ini = datetime.combine(dia, time())
    return ini, ini + timedelta(days=1)


def _epoch(ts: datetime) -> int:
    # horário de parede como se fosse UTC, a convenção do gráfico
    # (`ui.data.to_epoch`): o eixo mostra 09:00 quando o pregão abriu 09:00
    return int((ts - datetime(1970, 1, 1)).total_seconds())


def _instrumento(symbol: str) -> dict:
    # o YAML não muda com o app aberto, e a tela relê a cada volta da captura
    if symbol not in _INSTRUMENTOS:
        _INSTRUMENTOS[symbol] = db.load_instrument_yaml(symbol)
    return _INSTRUMENTOS[symbol]


def _ligacoes(con, portfolio_id: int, dia: date) -> list[dict]:
    """As ligações do portfólio que existiam no dia, com a cor de cada uma.

    A cor é o lugar da ligação entre TODAS as do portfólio, removidas
    inclusive: remover uma variante não pode repintar as outras no meio do
    pregão.
    """
    ini, fim = _limites(dia)
    linhas = con.execute(
        "SELECT pm.ligacao_id, pm.variante_id, ev.nome, pm.fase, pm.ligada, "
        "pm.adicionado_em, pm.removido_em, pm.contratos_demo, pm.contratos_real "
        "FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "WHERE pm.portfolio_id = ? ORDER BY pm.ligacao_id",
        [portfolio_id]).fetchall()
    out = []
    for i, (lig, vid, nome, fase, ligada, adic, rem, ctr_demo, ctr_real) in enumerate(linhas):
        if adic >= fim or (rem is not None and rem < ini):
            continue
        # contratos_demo/real NULL = a conta usa os contratos do plano
        out.append({"ligacao_id": int(lig), "variante_id": int(vid),
                    "nome": nome, "fase": fase, "ligada": bool(ligada),
                    "cor": i, "contratos_demo": None if ctr_demo is None
                    else int(ctr_demo),
                    "contratos_real": None if ctr_real is None else int(ctr_real)})
    return out
