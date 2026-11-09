"""Ordens: constantes e formatação usadas por todas as partes."""
from __future__ import annotations

from datetime import datetime

from dash import html

from ..cartao import dica, inteiro, nome_curto, num


# trava da conta (core.ordens.TRAVA): a marca na barra da perda do dia
TRAVA_PCT = 90
# faixas da barra da perda do dia da conta (controller): cinza, âmbar, rosa
ATENCAO_PCT, PERIGO_PCT = 60, 85
# atraso médio da ordem acima disto pinta de âmbar
ATRASO_LENTO_MS = 2000
# captura sem sinal de vida além disto: o comando da tela fica esperando
SEM_VIDA_S = 10

# Os eventos que o "Só problemas" mostra (controller).
PROBLEMAS = frozenset({"recusada", "perdida", "nao_entrou", "chamado",
                       "saida_recusada", "protecao_recusada", "incerta",
                       "conta_travada", "teste_falhou"})
# Passos internos do motor: a escrita adiantada (`*_enviando`) e o
# cancelamento de resto de ordem são o "como", não o "o quê" — o diário da
# tela mostra problemas e desfechos.
_INTERNOS = frozenset({"enviando", "saida_enviando", "protecao_enviando",
                       "cancelar_enviando", "cancelar_recusada"})
_COMANDOS_INTERNOS = frozenset({"zerar_tudo_cumprido", "envio_cumprido"})


# --------------------------------------------------------------- formatação
def _data(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _rs(v) -> str:
    """"+R$ 94", "-R$ 150", "R$ 0", "—"."""
    if v is None:
        return "—"
    corpo = inteiro(int(round(abs(v))))
    if round(v) == 0:
        return f"R$ {corpo}"
    return f"{'+' if v > 0 else '-'}R$ {corpo}"


def _reais(v) -> str:
    return "—" if v is None else f"R$ {inteiro(int(round(v)))}"


def _sinal(v) -> str:
    if v is None or round(v, 2) == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _preco(v) -> str:
    return "—" if v is None else inteiro(int(round(float(v))))


def _hora(v, segundos=False) -> str:
    ts = _data(v)
    if ts is None:
        return "—"
    return f"{ts:%H:%M:%S}" if segundos else f"{ts:%H:%M}"


def _decimal(v, casas=1) -> str:
    """1 → "1", 1.3 → "1,3", -2.0 → "-2", -0.04 → "0" (sem ",0" sobrando).

    Arredonda ANTES de olhar zero e inteiro: -0,04 testado cru não é
    inteiro e saía "-0,0"; 2,96 saía "3,0". `round` devolve -0.0, que é
    igual a 0, então o zero perde o sinal aqui."""
    if v is None:
        return "—"
    r = round(float(v), casas)
    if r == 0:
        return "0"
    if r == int(r):
        return str(int(r))
    return num(r, casas)


def _int_sinal(v) -> str:
    if v is None:
        return "—"
    v = int(round(v))
    return ("+" if v > 0 else "-" if v < 0 else "") + inteiro(abs(v))


def _idade_s(desde, agora) -> float | None:
    d = _data(desde)
    if d is None or agora is None:
        return None
    return (agora - d).total_seconds()


def _mmss(seg) -> str:
    seg = max(0, int(seg))
    return f"{seg // 60}:{seg % 60:02d}"


def _etiqueta(texto, tom="cinza", explica=None):
    return html.Span([texto] + ([dica(explica)] if explica else []),
                     className=f"av-tag av-tag-{tom}")


def subtitulo(titulo, explica=None, *direita):
    """Subtítulo dentro de uma aba da Operação (Demo, Papel, Eventos...),
    com o (?) e os controles do bloco à direita."""
    return html.Div([
        html.H4([titulo] + ([dica(explica)] if explica else []),
                className="op-sub-t"),
        *([html.Div(list(direita), className="op-sub-dir")] if direita else []),
    ], className="op-sub")


def _vazio(texto, explica):
    """Estado vazio curto: o rótulo na tela, o porquê no (?)."""
    return html.P([texto, dica(explica)], className="op-vazio-txt")


def _lado(lado) -> html.Span:
    """Compra verde, venda azul — em contorno. Rosa é problema, e vender
    não é problema."""
    compra = (lado or 0) > 0
    return html.Span("COMPRA" if compra else "VENDA",
                     className="ord-lado " + ("ord-lado-c" if compra
                                              else "ord-lado-v"))


def _ligacoes(ordens: dict) -> dict[int, dict]:
    """`ligacoes` do estado, com a chave de volta a inteiro (o JSON a
    devolve como texto)."""
    out = {}
    for k, v in ((ordens or {}).get("ligacoes") or {}).items():
        try:
            out[int(k)] = v or {}
        except (TypeError, ValueError):
            continue
    return out


def _nome(nomes, lig) -> str:
    if lig is None:
        return "automação"
    return (nomes or {}).get(lig) or f"#{lig}"


def _nome_tab(nome, classe="op-nome-tab") -> html.Span:
    """O nome curto da variante numa tabela; o inteiro no `title`."""
    nome = nome or "—"
    return html.Span(nome_curto(nome), className=classe, title=nome)
