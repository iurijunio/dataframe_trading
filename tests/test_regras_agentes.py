"""Prova que as instruções dos agentes continuam ligadas ao código.

Regra por área só carrega se o caminho dela bater com um arquivo. Arquivo
renomeado deixaria a regra muda, em silêncio; estes testes acusam isso.
"""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
REGRAS = RAIZ / ".claude" / "rules"
LIMITE_NUCLEO = 9_000
LIMITE_REGRA = 22_000


def _modulo(caminho: Path):
    spec = importlib.util.spec_from_file_location(caminho.stem, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rastreados() -> list[str]:
    saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    return [s for s in saida.splitlines() if (RAIZ / s).exists()]


def _casa(padrao: str, arquivo: str) -> bool:
    regex = re.escape(padrao).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, arquivo) is not None


def _paths(regra: Path) -> list[str]:
    cab = regra.read_text(encoding="utf-8").split("---")[1]
    return re.findall(r'^\s*-\s*"([^"]+)"', cab, flags=re.M)


def _regras() -> list[Path]:
    return sorted(REGRAS.glob("*.md"))


def _cobertas(arquivo: str) -> set[str]:
    return {r.stem for r in _regras() if any(_casa(p, arquivo) for p in _paths(r))}


def test_claude_md_importa_o_nucleo():
    assert "@AGENTS.md" in (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")


def test_nucleo_nao_volta_a_inchar():
    assert (RAIZ / "AGENTS.md").stat().st_size <= LIMITE_NUCLEO


def test_regra_nao_passa_do_limite():
    for r in _regras():
        assert r.stat().st_size <= LIMITE_REGRA, r.name


def test_toda_regra_declara_caminhos_e_todos_existem():
    rastreados = _rastreados()
    assert _regras()
    for r in _regras():
        paths = _paths(r)
        assert paths, f"{r.name} sem paths carregaria sempre"
        for p in paths:
            assert any(_casa(p, a) for a in rastreados), f"{r.name}: {p} não casa com nenhum arquivo"


def test_tabela_do_nucleo_lista_exatamente_as_regras():
    nucleo = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
    citadas = set(re.findall(r"\.claude/rules/([\w-]+)\.md", nucleo))
    assert citadas == {r.stem for r in _regras()}


def test_todo_caminho_citado_no_nucleo_existe():
    nucleo = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
    citados = re.findall(r"`((?:docs|tests|scripts|\.claude|core|ui)/[\w./-]+\.\w+)`", nucleo)
    assert citados
    for c in citados:
        assert (RAIZ / c).exists(), c


def test_nucleo_nao_cita_estrategia_especifica():
    nucleo = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
    assert not re.search(r"strategies/[a-z_]+\.py", nucleo)
    nomes = [p.stem for p in (RAIZ / "strategies").glob("*.py") if p.stem not in {"__init__", "registry", "base"}]
    for nome in nomes:
        assert nome not in nucleo, nome


@pytest.mark.parametrize("arquivo,regra", [
    ("captura.py", "captura-papel"),
    ("captura.py", "ordens"),
    ("ordens_real.py", "ordens"),
    ("core/ordens.py", "ordens"),
    ("core/corretora.py", "ordens"),
    ("core/ponte.py", "ordens"),
    ("core/ao_vivo.py", "ordens"),
    ("core/diario.py", "ordens"),
    ("core/db_manager.py", "ordens"),
    ("iniciar.bat", "ordens"),
    ("captura.bat", "captura-papel"),
    ("core/papel.py", "captura-papel"),
    ("core/papel_vivo.py", "captura-papel"),
    ("core/engine/kernel.py", "motor-estrategias"),
    ("core/optimizer.py", "mineracao"),
    ("core/busca/motor.py", "busca"),
    ("core/ativo.py", "cme"),
    ("core/portfolio.py", "portfolio"),
    ("ui/callbacks.py", "tela"),
    ("ui/assets/style.css", "tela"),
])
def test_arquivo_critico_carrega_a_regra(arquivo, regra):
    assert (RAIZ / arquivo).exists(), arquivo
    assert regra in _cobertas(arquivo)


def test_toda_estrategia_e_tela_tem_regra():
    for a in _rastreados():
        if a.startswith("strategies/") and a.endswith(".py"):
            assert "motor-estrategias" in _cobertas(a), a
        if a.startswith("ui/"):
            assert "tela" in _cobertas(a), a


# Guarda (.claude/hooks/guarda.py)

guarda = _modulo(RAIZ / ".claude" / "hooks" / "guarda.py")
FECHADO, ABERTO = (lambda: False), (lambda: True)


@pytest.mark.parametrize("comando", [
    "git add -A", "git add --all", "git add .", "git status; git add -A", "git -C x add .", "git add a.py .",
    "git add -u", "git commit -a -m x", "git commit -am x", "git commit --all",
])
def test_guarda_recusa_add_de_tudo(comando):
    for shell in ("Bash", "PowerShell"):
        assert guarda.decidir(shell, {"command": comando}, aberto=FECHADO)


@pytest.mark.parametrize("comando", [
    "git add AGENTS.md", "git add .claude/rules/tela.md", "git status", "git add ./a.py", "git commit -F msg.txt",
    "git commit -m x",
])
def test_guarda_libera_add_por_caminho(comando):
    assert guarda.decidir("Bash", {"command": comando}, aberto=FECHADO) is None


def test_guarda_recusa_copia_do_app_so_com_o_real_aberto():
    previa = {"name": "dataframe"}
    assert guarda.decidir("mcp__Claude_Browser__preview_start", previa, aberto=ABERTO)
    assert guarda.decidir("mcp__Claude_Browser__preview_start", previa, aberto=FECHADO) is None
    assert guarda.decidir("mcp__Claude_Browser__preview_start", {"url": "https://x"}, aberto=ABERTO) is None
    comando = {"command": ".venv/Scripts/python.exe ui/app.py"}
    assert guarda.decidir("Bash", comando, aberto=ABERTO)
    assert guarda.decidir("Bash", comando, aberto=FECHADO) is None
    assert guarda.decidir("Bash", {"command": "git log ui/app.py"}, aberto=ABERTO) is None
    assert guarda.decidir("Bash", {"command": "python -m py_compile ui/app.py"}, aberto=ABERTO) is None


@pytest.mark.parametrize("comando", [
    "rm -rf data", "rm -rf .claude/worktrees/x/data/", "rm -r .venv", 'Remove-Item -Recurse -Force "w/.venv"',
    "remove-item data -recurse",
])
def test_guarda_recusa_apagar_juncao(comando):
    assert guarda.decidir("Bash", {"command": comando}, aberto=FECHADO)


@pytest.mark.parametrize("comando", [
    "rm -rf build", "rm -rf data/foo", "cmd /c rmdir data", "rm data.txt", "Remove-Item -Recurse graphify-out",
])
def test_guarda_libera_outras_remocoes(comando):
    assert guarda.decidir("Bash", {"command": comando}, aberto=FECHADO) is None


def test_guarda_recusa_leitura_inteira_so_de_arquivo_grande():
    grande, pequeno = (lambda _: guarda.LIMITE_LINHAS + 1), (lambda _: guarda.LIMITE_LINHAS)
    assert guarda.decidir("Read", {"file_path": "a.py"}, linhas=grande)
    assert guarda.decidir("Read", {"file_path": "a.py"}, linhas=pequeno) is None
    assert guarda.decidir("Read", {"file_path": "a.py", "offset": 10}, linhas=grande) is None
    assert guarda.decidir("Read", {"file_path": "a.py", "limit": 10}, linhas=grande) is None
    assert guarda.decidir("Read", {"file_path": "a.py", "allow_large": True}, linhas=grande) is None
    assert guarda.decidir("Read", {"file_path": "a.png"}, linhas=grande) is None


def test_guarda_nao_recusa_outras_ferramentas():
    assert guarda.decidir("Edit", {"file_path": "a.py"}, aberto=ABERTO) is None


# Conferir (scripts/conferir.py)

conferir = _modulo(RAIZ / "scripts" / "conferir.py")


def test_conferir_motor_e_estrategia():
    plano = conferir.o_que_conferir(["core/engine/kernel.py"])
    assert any("gabarito_motor" in c for c in plano["rodar"])
    assert any("foto_win" in c for c in plano["lembrar"])
    assert not any("reassinar" in c for c in plano["lembrar"])
    assert any("reassinar" in c for c in conferir.o_que_conferir(["strategies/x.py"])["lembrar"])


@pytest.mark.parametrize("arquivo,trecho", [
    ("ui/callbacks_ordens.py", "test_callbacks_sem_ciclo"),
    ("ui/components/mine_regiao.py", "campos_menu"),
    ("ui/components/portfolio_panel.py", "referencia_telas"),
])
def test_conferir_tela(arquivo, trecho):
    assert any(trecho in c for c in conferir.o_que_conferir([arquivo])["rodar"])


@pytest.mark.parametrize("arquivo,janela", [
    ("core/ordens.py", "Ordens real"),
    ("ordens_real.py", "Ordens real"),
    ("core/papel_vivo.py", "Ordens real"),
    ("captura.py", "Captura"),
    ("core/schema.sql", "Captura"),
    ("strategies/x.py", "Captura"),
    ("core/engine/kernel.py", "Captura"),
    ("core/mt5_source.py", "Captura"),
    ("core/conferencia_ordens.py", "Captura"),
    ("core/comandos.py", "Ordens real"),
    ("core/diario_ordens.py", "Ordens real"),
    ("core/portfolio.py", "iniciar.bat"),
    ("ui/assets/style.css", "iniciar.bat"),
])
def test_conferir_diz_o_que_reabrir(arquivo, janela):
    reabrir = conferir.o_que_conferir([arquivo])["reabrir"]
    assert len(reabrir) == 1 and janela in reabrir[0]


def test_conferir_doc_nao_pede_nada():
    assert not any(conferir.o_que_conferir(["docs/x.md", "AGENTS.md"]).values())
