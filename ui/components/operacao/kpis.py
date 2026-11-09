"""Operação: os números do topo (KPIs)."""
from __future__ import annotations

from dash import html

from ..cartao import dica

from .base import _rotulo, _rs, _sinal


# ------------------------------------------------------------------- KPIs
def _kpi(rotulo, explica, valor, nota=None, sinal=None, barra=None,
         nota_title=None, ordem=None):
    filhos = [_rotulo(rotulo, explica, "op-kpi-r"),
              html.Span(valor, className="op-kpi-v"
                        + (f" {sinal}" if sinal else ""))]
    if nota:
        filhos.append(html.Span(nota, className="op-kpi-n",
                                title=nota_title or ""))
    if barra is not None:
        filhos.append(barra)
    # a ordem na tira de seis números (REAL, DEMO, PAPEL, perdas, esperado)
    estilo = {"order": ordem} if ordem is not None else None
    return html.Div(filhos, className="op-kpi", style=estilo)


def _barra(uso_pct: float):
    tom = "ok" if uso_pct < 50 else ("atencao" if uso_pct < 80 else "perigo")
    largura = f"{min(100, round(uso_pct))}%"
    return html.Div(html.Span(className=f"op-barra-uso op-barra-{tom}",
                              style={"width": largura}),
                    className="op-barra")


def kpis(resumo: dict, ops: list[dict], esperado: dict,
         nomes: dict | None = None) -> list:
    """Os dois números do papel na tira (protótipo v2, Operação): PAPEL hoje,
    com o total desde o plano em vigor embaixo, e Contra o esperado. Os
    números das contas (REAL e DEMO hoje, as perdas do dia) saem do pulso
    (`ordens_panel.numeros`) e entram na mesma tira pela ordem CSS.

    `esperado` = {"diferenca": papel − soma das medianas, "faixas": faixa
    atual de cada variante}. `ops` e `nomes` ficam na assinatura: o
    redesenho os passa e a tela usa só o resumo."""
    hoje = resumo.get("resultado_hoje") or 0.0
    acum = resumo.get("acumulado") or {}

    dif = (esperado or {}).get("diferenca")
    faixas = [f for f in (esperado or {}).get("faixas") or [] if f]
    if dif is None:
        valor_esp, sinal_esp = "—", None
        nota_esp = (esperado or {}).get("aviso") or "plano sem expectativa gravada"
        title_esp = nota_esp
    else:
        valor_esp, sinal_esp = _rs(dif), _sinal(dif)
        mediana = f"{'acima' if dif >= 0 else 'abaixo'} da mediana"
        nota_esp, partes = mediana, [mediana]
        if faixas:
            dentro = sum(1 for f in faixas if f in ("p10_p50", "p50_p90"))
            baixo = faixas.count("abaixo_p10")
            alto = faixas.count("acima_p90")
            partes.append(f"{dentro} de {len(faixas)} dentro da faixa")
            if baixo:
                partes.append(f"{baixo} abaixo do p10")
            if alto:
                partes.append(f"{alto} acima do p90")
            # na nota só o que mais importa: quem está abaixo do p10 primeiro
            nota_esp = (f"{baixo} abaixo do p10" if baixo
                        else f"{dentro} de {len(faixas)} dentro da faixa")
        title_esp = " · ".join(partes)

    total = acum.get("valor")
    pregoes = acum.get("pregoes", 0)
    operacoes = acum.get("operacoes", 0)
    explica_papel = (
        "Soma do papel de hoje das variantes: operações fechadas mais a aberta "
        "pelo preço do último candle (provisório). Operação fora do período em "
        "que a variante estava ligada não entra. Bom: positivo. Ruim: perto do "
        "limite de perda do dia. O total embaixo é o acumulado do papel desde o "
        "plano em vigor (recomeça quando o plano muda), com a operação aberta "
        "pelo valor provisório: "
        f"{pregoes} {'pregão' if pregoes == 1 else 'pregões'} e "
        f"{operacoes} {'operação' if operacoes == 1 else 'operações'}. Bom: "
        "dentro ou acima da faixa esperada. Ruim: abaixo do p10.")
    return [
        _kpi_papel(hoje, total, explica_papel),
        _kpi("Contra o esperado",
             "Papel acumulado menos a soma das medianas que a Candidata "
             "prometeu para o mesmo número de pregões. Por variante, a faixa "
             "em que ela está: p10 = em 10% dos sorteios da Candidata o "
             "resultado ficou abaixo disso. Bom: entre p10 e p90. Ruim: "
             "abaixo do p10 — o papel está pior que 9 em 10 cenários.",
             valor_esp, nota_esp, "aviso" if "abaixo_p10" in faixas
             else sinal_esp, nota_title=title_esp, ordem=6),
    ]


def _kpi_papel(hoje, total, explica) -> html.Div:
    """PAPEL hoje: o resultado do dia do papel e, embaixo, o total desde o
    plano em vigor (verde ou vermelho)."""
    rot = html.Span([html.Span("PAPEL", className="op-acc op-acc-papel"),
                     " hoje", dica(explica)], className="op-kpi-r")
    return html.Div([
        rot,
        html.Span(_rs(hoje), className="op-kpi-v"
                  + (f" {_sinal(hoje)}" if _sinal(hoje) else "")),
        html.Span(["total ", html.B(_rs(total, 2),
                                    className=_sinal(total) or "")],
                  className="op-kpi-n"),
    ], className="op-kpi op-kpi-conta", style={"order": 3})
