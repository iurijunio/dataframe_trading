"""Prova dos campos do menu: o menu pode mudar de lugar, nenhum campo pode sumir.

    python scripts/campos_menu.py gravar     (grava tests/dados/campos_menu.json)
    python scripts/campos_menu.py conferir   (exit 1 se algum campo diferir)

`extrair` percorre uma árvore Dash e devolve cada campo (dcc.Input, Dropdown,
Checklist, DatePickerSingle, RadioItems com id) com id, valor, faixa, opções e
rótulo — ordenado pelo id, sem olhar onde o campo está na árvore. `menu`
monta o menu como o app monta para um ativo e uma estratégia, sem banco e
sem estado global (datas e instrumentos fixos).

O JSON em tests/dados/campos_menu.json foi gravado do menu ANTIGO (barra
lateral única) e nunca é regravado: é a régua do menu novo.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dash import dcc, html  # noqa: E402

ARQUIVO = RAIZ / "tests" / "dados" / "campos_menu.json"
INICIO = datetime(2021, 3, 16)
FIM = datetime(2026, 10, 30)
INSTRUMENTOS = ["WIN$N", "MES", "MNQ"]

CAMPOS = (dcc.Input, dcc.Dropdown, dcc.Checklist, dcc.DatePickerSingle,
          dcc.RadioItems)
IDS_NOVOS = {"menu-aba", "mine-subtela"}
TIPOS_NOVOS = {"menu-pane", "gaveta", "gaveta-resumo"}


def _id_canonico(i) -> str:
    return json.dumps(i, sort_keys=True) if isinstance(i, dict) else str(i)


def _ignorado(i) -> bool:
    if isinstance(i, dict):
        return i.get("type") in TIPOS_NOVOS
    return i in IDS_NOVOS


def _filhos(c) -> list:
    f = getattr(c, "children", None)
    if f is None:
        return []
    return list(f) if isinstance(f, (list, tuple)) else [f]


def _texto(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, (int, float)):
        return str(c)
    if c is None or "dica-mark" in (getattr(c, "className", None) or "").split():
        return ""
    return "".join(_texto(f) for f in _filhos(c))


def _eh_fld(c) -> bool:
    return isinstance(c, html.Div) and "fld" in (getattr(c, "className", None) or "").split()


def _rotulo_de(fld) -> str | None:
    """Texto do primeiro html.Label do .fld, sem descer em .fld aninhado."""
    for f in _filhos(fld):
        if isinstance(f, html.Label):
            return _texto(f).strip()
        if hasattr(f, "children") and not _eh_fld(f):
            r = _rotulo_de(f)
            if r is not None:
                return r
    return None


def _valores(opcoes) -> list | None:
    if opcoes is None:
        return None
    return [o["value"] if isinstance(o, dict) else o for o in opcoes]


def _json(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _campo(c, rotulo) -> dict:
    tipo = type(c).__name__
    d = {"id": _id_canonico(c.id), "tipo": tipo}
    if isinstance(c, dcc.DatePickerSingle):
        d["date"] = _json(c.date)
        d["min"] = _json(c.min_date_allowed)
        d["max"] = _json(c.max_date_allowed)
        d["step"] = None
    else:
        d["value"] = c.value
        d["min"] = getattr(c, "min", None)
        d["max"] = getattr(c, "max", None)
        d["step"] = getattr(c, "step", None)
    d["options"] = _valores(getattr(c, "options", None))
    d["rotulo"] = rotulo
    return d


def extrair(arvore) -> list[dict]:
    achados: list[dict] = []

    def anda(c, rotulo):
        if isinstance(c, (list, tuple)):
            for x in c:
                anda(x, rotulo)
            return
        if not hasattr(c, "children") and not isinstance(c, CAMPOS):
            return
        if _eh_fld(c):
            rotulo = _rotulo_de(c)
        i = getattr(c, "id", None)
        if isinstance(c, CAMPOS) and i is not None and not _ignorado(i):
            achados.append(_campo(c, rotulo))
        for f in _filhos(c):
            anda(f, rotulo)

    anda(arvore, None)
    return sorted(achados, key=lambda d: d["id"])


def _aplicar_camada4(arvore, simbolo) -> None:
    """Stop, alvo e trailing como a tela fica ao escolher o ativo
    (`callbacks._tabela_c4`): valor, faixa e step de cada caixa."""
    from ui import callbacks

    tabela = callbacks._tabela_c4(simbolo)

    def anda(c):
        if isinstance(c, (list, tuple)):
            for x in c:
                anda(x)
            return
        i = getattr(c, "id", None)
        if (isinstance(c, dcc.Input) and isinstance(i, dict)
                and i.get("p") in tabela and i.get("type") in ("val", "opt")):
            t = tabela[i["p"]]
            c.value = t["valor"] if i["type"] == "val" else t[i["k"]]
            c.step = t["step"]
        for f in _filhos(c):
            anda(f)

    anda(arvore)


def menu(simbolo: str, estrategia: str) -> list[dict]:
    """O menu novo (topo fixo + abas), como `ui.app.sidebar` o monta."""
    from core import ativo as ativo_mod
    from strategies import registry
    from ui.components import controls

    mod = registry.carregar(estrategia)
    with mock.patch.object(registry, "nome_atual", lambda: estrategia):
        blocos = [
            controls.topo_menu(simbolo, INICIO, FIM, ativos=INSTRUMENTOS),
            controls.abas_menu(mod, ativo_mod.faixas_do_ativo(simbolo, estrategia)),
        ]
    _aplicar_camada4(blocos, simbolo)
    return extrair(blocos)


def todos() -> dict:
    from strategies import registry

    return {f"{s}|{e['modulo']}": menu(s, e["modulo"])
            for e in registry.descobrir() for s in INSTRUMENTOS}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("gravar", "conferir"):
        print(__doc__)
        return 2
    atual = todos()
    if argv[0] == "gravar":
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        ARQUIVO.write_text(json.dumps(atual, indent=1, ensure_ascii=False,
                                      sort_keys=True) + "\n", encoding="utf-8")
        print(f"gravado: {ARQUIVO} ({len(atual)} pares)")
        return 0
    ref = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    ruins = [k for k in sorted(set(ref) | set(atual))
             if json.loads(json.dumps(atual.get(k))) != ref.get(k)]
    print("iguais" if not ruins else "diferem: " + ", ".join(ruins))
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
