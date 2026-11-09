"""Leitura: pregão e plano do dia, e o seletor de pregões."""
from __future__ import annotations

from datetime import date

from .. import plano as _plano
from .. import variantes as V

from .base import _PREGOES_QUE_CONTAM, _ligacoes


def _pregao(con, ligacao_id: int, dia: date):
    """(plano_id, status, motivo, falha) gravados do pregão, ou Nones."""
    r = con.execute("SELECT plano_id, status, motivo, falha FROM papel_pregoes "
                    "WHERE ligacao_id = ? AND dia = ?",
                    [ligacao_id, dia]).fetchone()
    return tuple(r) if r else (None, None, None, None)


def _plano_do_dia(con, variante_id: int, dia: date,
                  gravado: int | None) -> dict | None:
    """O plano com que o papel rodou no dia (o gravado no pregão manda: é o
    que o motor de fato usou), senão o que está em vigor."""
    pid = gravado
    if pid is None:
        vigor = V.plano_em_vigor(variante_id, dia, con=con)
        pid = vigor["plano_id"] if vigor else None
    return None if pid is None else _plano.detalhes(int(pid), con=con)


def _desde_o_plano(plano: dict) -> tuple[str, list]:
    """Filtro SQL "papel deste plano, desde que ele vale"."""
    vale = plano.get("vale_a_partir")
    return ("plano_id = ? AND (CAST(? AS DATE) IS NULL OR dia >= ?)",
            [plano["plano_id"], vale, vale])


def _acumulado(con, ligacao_id: int, plano: dict | None, ate: date) -> dict:
    """Papel que conta desde o plano em vigor. INCLUI a aberta provisória,
    para que acumulado menos ontem dê o resultado de hoje — diferente do
    `comparativo`, que só olha fechadas."""
    if plano is None:
        return {"valor": 0.0, "operacoes": 0, "dias": set()}
    filtro, args = _desde_o_plano(plano)
    valor, n = con.execute(
        "SELECT coalesce(sum(liquido), 0), count(*) FROM papel_operacoes "
        f"WHERE ligacao_id = ? AND conta AND dia <= ? AND {filtro}",
        [ligacao_id, ate, *args]).fetchone()
    dias = {r[0] for r in con.execute(
        "SELECT dia FROM papel_pregoes WHERE ligacao_id = ? AND dia <= ? "
        f"AND status IN {_PREGOES_QUE_CONTAM} AND {filtro}",
        [ligacao_id, ate, *args]).fetchall()}
    return {"valor": float(valor), "operacoes": int(n), "dias": dias}


_COLS_OP = ("op_id", "ligacao_id", "plano_id", "entry_ts", "exit_ts", "side",
            "contratos", "entry_px", "exit_px", "points", "liquido", "reason",
            "stop_px", "alvo_px", "aberta", "conta")


def _ops_do_dia(con, ligacoes: list[int], dia: date) -> list[dict]:
    if not ligacoes:
        return []
    linhas = con.execute(
        f"SELECT {', '.join(_COLS_OP)} FROM papel_operacoes WHERE dia = ? "
        f"AND ligacao_id IN ({', '.join('?' * len(ligacoes))}) "
        "ORDER BY entry_ts, ligacao_id", [dia, *ligacoes]).fetchall()
    return [dict(zip(_COLS_OP, r)) for r in linhas]


_MOTIVO_PRESO = "pregão não foi conferido: números da última volta"

# Situação, na tabela do dia, da operação que está `aberta` no banco mas
# não é posição de agora — pelo status do pregão para a tela. A "nota" diz
# o porquê na linha; stop/alvo dela não se desenham (não são os vigentes).
_ABERTA_PARADA = {"nao_conferido": ("nao_conferido", "pregão não conferido"),
                  "falha": ("nao_atualizada", "falha no cálculo"),
                  "interrompido": ("congelada", "código mudou")}


def _situacao(status: str | None, dia: date, hoje: date,
              falha: str | None = None) -> tuple:
    """(status para a tela, vivo?). Pregão passado ainda `rodando` não é
    pregão vivo: é a conferência que não fechou o dia. Nem o de hoje cujo
    último cálculo falhou: o gravado é de antes da falha, e a aberta dele
    tem o stop/alvo de quando o motor ainda rodava."""
    if status == "rodando" and dia < hoje:
        return "nao_conferido", False
    if status == "rodando" and falha:
        return "falha", False
    return status, status == "rodando" and dia >= hoje


def _por_ligacao(con, portfolio_id: int, dia: date, hoje: date) -> list[dict]:
    """O que a tela mostra de cada ligação no dia — base de `resumo`,
    `variantes` e `alertas`, para os três nunca discordarem."""
    ligs = _ligacoes(con, portfolio_id, dia)
    ops = _ops_do_dia(con, [l["ligacao_id"] for l in ligs], dia)
    out = []
    for l in ligs:
        lig = l["ligacao_id"]
        gravado, status, motivo, falha = _pregao(con, lig, dia)
        p = _plano_do_dia(con, l["variante_id"], dia, gravado)
        status, vivo = _situacao(status, dia, hoje, falha)
        if status == "nao_conferido":
            motivo = _MOTIVO_PRESO
        elif status == "falha":
            motivo = falha
        minhas = [o for o in ops if o["ligacao_id"] == lig and o["conta"]]
        fechadas = [o for o in minhas if not o["aberta"]]
        posicao = sum(int(o["side"]) * int(o["contratos"])
                      for o in minhas if o["aberta"]) if vivo else 0
        out.append({
            **l, "status": status, "motivo": motivo, "vivo": vivo,
            "posicao": posicao,
            "hoje": float(sum(o["liquido"] or 0.0 for o in minhas)),
            "n_ops": len(minhas),
            "acerto": (f"{sum(1 for o in fechadas if (o['liquido'] or 0) > 0)}"
                       f"/{len(fechadas)}"),
            "acumulado_det": _acumulado(con, lig, p, dia),
            "contratos": int(p["contratos"]) if p and p["contratos"] else None,
            "plano_id": p and p["plano_id"],
            "gravado_mesmo_assim": bool(p and p["gravado_mesmo_assim"]),
            "pendencias": (p and p["pendencias"]) or [],
            "_ops": minhas, "_plano": p,
        })
    return out


# ------------------------------------------------------------- seletor
def portfolios_com_papel(con) -> list[dict]:
    """Todos os portfólios, para o seletor — inclusive o sem ligação, que a
    tela mostra vazio com a explicação (spec §7)."""
    return [{"portfolio_id": int(r[0]), "nome": r[1], "ligado": bool(r[2])}
            for r in con.execute(
                "SELECT portfolio_id, nome, coalesce(ligado, false) "
                "FROM portfolios ORDER BY nome, portfolio_id").fetchall()]
