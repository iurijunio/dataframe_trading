"""As telas do WIN continuam escrevendo exatamente o que escreviam.

`scripts/referencia_telas.py gravar` foi rodado antes de a moeda entrar nas
funções de tela; `conferir` compara o que elas devolvem agora com o gravado em
`tests/dados/telas_win/`. Se um texto, um número ou o JSON de uma figura do WIN
mudar, este teste mostra qual.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import referencia_telas as R  # noqa: E402


def test_telas_do_win_identicas_a_referencia():
    difs = R.conferir()
    assert difs == [], "\n".join(difs[:20])


def test_conferir_acusa_a_diferenca(tmp_path, monkeypatch):
    """Sem isto o teste acima poderia passar vazio: aqui uma referência
    adulterada tem que ser notada."""
    import json
    import shutil

    copia = tmp_path / "telas_win"
    shutil.copytree(R.PASTA, copia)
    arq = copia / "metricas.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    dados["format_panel_vazio"] = "outro texto"
    arq.write_text(json.dumps(dados), encoding="utf-8")
    monkeypatch.setattr(R, "PASTA", copia)

    difs = R.conferir()
    assert len(difs) == 1 and difs[0].startswith("metricas/format_panel_vazio")


def test_conferir_acusa_referencia_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "PASTA", tmp_path / "vazia")
    assert all("sem referência" in d for d in R.conferir())
