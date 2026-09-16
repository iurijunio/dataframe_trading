"""Tabela de trades - AG Grid Community.

Scroll virtual porque a lista passa de 20 mil linhas com facilidade, e
selecao de linha como evento: clicar num trade leva o grafico ate ele.
"""

from __future__ import annotations

import dash_ag_grid as dag
import numpy as np

from core.engine import kernel as K

# Formato brasileiro: 1.234,56. O d3.format padrao devolveria 1,234.56.
BRL = {
    "function": "params.value == null ? '' : params.value.toLocaleString('pt-BR', "
                "{minimumFractionDigits: 2, maximumFractionDigits: 2})"
}
INT = {"function": "params.value == null ? '' : params.value.toLocaleString('pt-BR')"}

COLUNAS = [
    {"field": "n", "headerName": "#", "width": 78, "pinned": "left"},
    {"field": "entrada", "headerName": "entrada", "width": 145},
    {"field": "saida", "headerName": "saída", "width": 145},
    {"field": "lado", "headerName": "lado", "width": 84,
     "cellClassRules": {"lado-c": "params.value == 'compra'",
                        "lado-v": "params.value == 'venda'"}},
    {"field": "preco_ent", "headerName": "preço ent.", "width": 110,
     "type": "numericColumn", "valueFormatter": INT},
    {"field": "preco_sai", "headerName": "preço saí.", "width": 110,
     "type": "numericColumn", "valueFormatter": INT},
    {"field": "pontos", "headerName": "pontos", "width": 100, "type": "numericColumn",
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "liquido", "headerName": "líquido R$", "width": 120, "type": "numericColumn",
     "valueFormatter": BRL,
     "cellClassRules": {"pos": "params.value > 0", "neg": "params.value < 0"}},
    {"field": "contratos", "headerName": "ctr", "width": 76, "type": "numericColumn"},
    {"field": "motivo", "headerName": "saída por", "width": 130},
    {"field": "barras", "headerName": "barras", "width": 92, "type": "numericColumn"},
    {"field": "mae", "headerName": "MAE", "width": 92, "type": "numericColumn"},
    {"field": "mfe", "headerName": "MFE", "width": 92, "type": "numericColumn"},
]


def rows(trades: dict, dinheiro: dict) -> list[dict]:
    if not trades or not len(trades["entry_i"]):
        return []
    # ISO fica nos campos ocultos, que o callback usa para mover o grafico;
    # a coluna visivel mostra a data no formato daqui.
    iso_e = np.datetime_as_string(trades["entry_ts"], unit="m")
    iso_s = np.datetime_as_string(trades["exit_ts"], unit="m")
    br = lambda s: f"{s[8:10]}/{s[5:7]}/{s[:4]}  {s[11:]}"
    return [
        {
            "n": i + 1,
            "idx": i,
            "t_ent": str(iso_e[i]),
            "t_sai": str(iso_s[i]),
            "entrada": br(str(iso_e[i])),
            "saida": br(str(iso_s[i])),
            "lado": "compra" if trades["side"][i] == 1 else "venda",
            "preco_ent": int(trades["entry_px"][i]),
            "preco_sai": int(trades["exit_px"][i]),
            "pontos": int(trades["points"][i]),
            "liquido": round(float(dinheiro["liquido"][i]), 2),
            "contratos": int(dinheiro["contratos"][i]),
            "motivo": K.EXIT_LABELS[int(trades["reason"][i])],
            "barras": int(trades["bars_held"][i]),
            "mae": int(trades["mae"][i]),
            "mfe": int(trades["mfe"][i]),
        }
        for i in range(len(trades["entry_i"]))
    ]


def grid(id_: str = "grid-trades"):
    """`id_` existe para a MESMA tabela poder aparecer em dois lugares — o
    Backtest e a sub-aba da vencedora no Walk-Forward — sem colidir."""
    return dag.AgGrid(
        id=id_,
        columnDefs=COLUNAS,
        rowData=[],
        className="ag-theme-alpine-dark grid-trades",
        dashGridOptions={
            "rowSelection": "single",
            "animateRows": False,
            "rowHeight": 30,
            "headerHeight": 34,
            "suppressCellFocus": True,
            "localeText": {"noRowsToShow": "Nenhum trade."},
        },
        defaultColDef={"sortable": True, "filter": True, "resizable": True},
        columnSize="responsiveSizeToFit",
        style={"height": "100%", "width": "100%"},
    )
