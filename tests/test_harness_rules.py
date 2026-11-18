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
    ("captura.py", "capture-paper"),
    ("captura.py", "orders"),
    ("ordens_real.py", "orders"),
    ("core/ordens.py", "orders"),
    ("core/corretora.py", "orders"),
    ("core/ponte.py", "orders"),
    ("core/ao_vivo.py", "orders"),
    ("core/diario.py", "orders"),
    ("core/db_manager.py", "orders"),
    ("iniciar.bat", "orders"),
    ("captura.bat", "capture-paper"),
    ("core/papel.py", "capture-paper"),
    ("core/papel_vivo.py", "capture-paper"),
    ("core/engine/kernel.py", "engine-strategies"),
    ("core/optimizer.py", "mining"),
    ("core/busca/motor.py", "search"),
    ("core/ativo.py", "cme"),
    ("core/portfolio.py", "portfolio"),
    ("ui/callbacks.py", "ui"),
    # os pacotes que vieram das cascas carregam a mesma regra delas
    ("ui/components/ordens/base.py", "orders"),
    ("ui/components/ao_vivo/ficha.py", "orders"),
    ("core/leitura/demo.py", "capture-paper"),
    ("ui/cb_operacao/tela.py", "capture-paper"),
    ("ui/components/operacao/bloco.py", "capture-paper"),
    ("ui/assets/style.css", "ui"),
])
def test_arquivo_critico_carrega_a_regra(arquivo, regra):
    assert (RAIZ / arquivo).exists(), arquivo
    assert regra in _cobertas(arquivo)


def test_toda_estrategia_e_tela_tem_regra():
    for a in _rastreados():
        if a.startswith("strategies/") and a.endswith(".py"):
            assert "engine-strategies" in _cobertas(a), a
        if a.startswith("ui/"):
            assert "ui" in _cobertas(a), a


# Teto de tamanho: arquivo grande custa leitura a todo agente.

TETO_LINHAS = 500
# Acima do teto em 09/11/2026. Só pode diminuir: dividiu, baixe ou tire daqui.
GRANDES = {
    "captura.py": 1774, "core/ao_vivo.py": 895, "core/busca/motor.py": 532, "core/candidata.py": 875,
    "core/engine/execution.py": 723, "core/optimizer.py": 870, "core/ordem_teste.py": 587, "core/ordens.py": 1769,
    "core/papel.py": 939, "core/plano.py": 585, "core/portfolio.py": 671,
    "core/wfa.py": 1548, "ordens_real.py": 550, "scripts/screens_reference.py": 683, "ui/assets/busca.js": 1064,
    "ui/assets/style.css": 2204, "ui/callbacks_ao_vivo.py": 595,
    "ui/callbacks_busca.py": 572, "ui/callbacks_candidata.py": 674,
 "ui/components/candidata_panel.py": 661,
   
    "ui/components/portfolio_panel.py": 511, "ui/components/wfa_panel.py": 1207,
}


def test_arquivo_de_codigo_respeita_o_teto():
    # Testes ficam de fora: são lidos por trecho, perto do teste que falhou.
    acima = {}
    for a in _rastreados():
        if a.endswith((".py", ".js", ".css")) and not a.startswith("tests/"):
            n = len((RAIZ / a).read_text(encoding="utf-8").splitlines())
            if n > GRANDES.get(a, TETO_LINHAS):
                acima[a] = n
    assert acima == {}, "acima do teto (ou cresceu): divida o arquivo"


def test_lista_de_grandes_nao_tem_sobra():
    for a, limite in GRANDES.items():
        assert limite > TETO_LINHAS, a
        assert (RAIZ / a).exists(), f"{a} sumiu: tire da lista"


# Guard (.claude/hooks/guard.py)

guard = _modulo(RAIZ / ".claude" / "hooks" / "guard.py")
FECHADO, ABERTO = (lambda: False), (lambda: True)


@pytest.mark.parametrize("comando", [
    "git add -A", "git add --all", "git add .", "git status; git add -A", "git -C x add .", "git add a.py .",
    "git add -u", "git commit -a -m x", "git commit -am x", "git commit --all",
])
def test_guarda_recusa_add_de_tudo(comando):
    for shell in ("Bash", "PowerShell"):
        assert guard.decide(shell, {"command": comando}, is_open=FECHADO)


@pytest.mark.parametrize("comando", [
    "git add AGENTS.md", "git add .claude/rules/ui.md", "git status", "git add ./a.py", "git commit -F msg.txt",
    "git commit -m x",
])
def test_guarda_libera_add_por_caminho(comando):
    assert guard.decide("Bash", {"command": comando}, is_open=FECHADO) is None


def test_guarda_recusa_copia_do_app_so_com_o_real_aberto():
    previa = {"name": "dataframe"}
    assert guard.decide("mcp__Claude_Browser__preview_start", previa, is_open=ABERTO)
    assert guard.decide("mcp__Claude_Browser__preview_start", previa, is_open=FECHADO) is None
    assert guard.decide("mcp__Claude_Browser__preview_start", {"url": "https://x"}, is_open=ABERTO) is None
    comando = {"command": ".venv/Scripts/python.exe ui/app.py"}
    assert guard.decide("Bash", comando, is_open=ABERTO)
    assert guard.decide("Bash", comando, is_open=FECHADO) is None
    assert guard.decide("Bash", {"command": "git log ui/app.py"}, is_open=ABERTO) is None
    assert guard.decide("Bash", {"command": "python -m py_compile ui/app.py"}, is_open=ABERTO) is None


@pytest.mark.parametrize("comando", [
    "rm -rf data", "rm -rf .claude/worktrees/x/data/", "rm -r .venv", 'Remove-Item -Recurse -Force "w/.venv"',
    "remove-item data -recurse",
])
def test_guarda_recusa_apagar_juncao(comando):
    assert guard.decide("Bash", {"command": comando}, is_open=FECHADO)


@pytest.mark.parametrize("comando", [
    "rm -rf build", "rm -rf data/foo", "cmd /c rmdir data", "rm data.txt", "Remove-Item -Recurse graphify-out",
])
def test_guarda_libera_outras_remocoes(comando):
    assert guard.decide("Bash", {"command": comando}, is_open=FECHADO) is None


def test_guarda_recusa_leitura_inteira_so_de_arquivo_grande():
    grande, pequeno = (lambda _: guard.LINE_LIMIT + 1), (lambda _: guard.LINE_LIMIT)
    assert guard.decide("Read", {"file_path": "a.py"}, line_count=grande)
    assert guard.decide("Read", {"file_path": "a.py"}, line_count=pequeno) is None
    assert guard.decide("Read", {"file_path": "a.py", "offset": 10}, line_count=grande) is None
    assert guard.decide("Read", {"file_path": "a.py", "limit": 10}, line_count=grande) is None
    assert guard.decide("Read", {"file_path": "a.py", "allow_large": True}, line_count=grande) is None
    assert guard.decide("Read", {"file_path": "a.png"}, line_count=grande) is None


@pytest.mark.parametrize("comando", [
    ".venv/Scripts/python.exe ordens_real.py",
    "python captura.py",
    '& ".venv\\Scripts\\python.exe" C:\\x\\dataframe_trading\\ordens_real.py',
    ".venv/Scripts/python.exe -u captura.py --x",
    "cmd /c iniciar.bat",
    ".\\captura.bat",
    "./ordens_real.bat",
    "Start-Process ordens_real.bat",
    "start iniciar.bat",
    "cd x; call captura.bat",
])
def test_guarda_recusa_o_que_pode_operar_a_conta(comando):
    for shell in ("Bash", "PowerShell"):
        assert guard.decide(shell, {"command": comando}, is_open=FECHADO), comando


@pytest.mark.parametrize("comando", [
    ".venv/Scripts/python.exe -m pytest -q tests/test_captura_ordens.py",
    ".venv/Scripts/python.exe -m pytest -q tests/test_ordens.py -k order_send",
    ".venv/Scripts/python.exe scripts/check_changes.py core/ordens.py ordens_real.py",
    "git diff -- ordens_real.py captura.py iniciar.bat",
    "grep -n order_send core/ordens.py",
    "cat ordens_real.bat",
    "Get-Content iniciar.bat",
    "python -m py_compile captura.py",
    "python -c \"import duckdb\"",
    # A trava por menção ao MT5 saiu a pedido do usuário (09/11/2026): barrava análise só de leitura.
    "python -c \"from core import corretora\"",
    "python - <<'EOF'\nimport core.ordens\nEOF",
])
def test_guarda_libera_testes_e_leitura_do_codigo_de_ordens(comando):
    assert guard.decide("Bash", {"command": comando}, is_open=FECHADO) is None, comando


@pytest.mark.parametrize("comando", [
    "rm data/ao_vivo/ordens/2026-11-09.jsonl",
    "rm -rf data/ao_vivo",
    "Remove-Item data\\ao_vivo\\ordens\\*.jsonl",
    "del data\\ao_vivo\\ordens\\x.jsonl",
    "mv data/ao_vivo/ordens/x.jsonl /tmp/",
    "Move-Item data\\ao_vivo\\ordens\\x.jsonl y",
    "Clear-Content data/ao_vivo/ordens/x.jsonl",
    "Set-Content data/ao_vivo/ordens/x.jsonl ''",
    "echo {} > data/ao_vivo/ordens/x.jsonl",
    "echo {} >> data/ao_vivo/ordens/x.jsonl",
    "cmd /c rmdir /s /q data\\ao_vivo\\ordens",
    "python -c \"import os; os.remove('data/ao_vivo/ordens/x.jsonl')\"",
])
def test_guarda_recusa_mexer_no_diario_de_ordens(comando):
    for shell in ("Bash", "PowerShell"):
        assert guard.decide(shell, {"command": comando}, is_open=FECHADO), comando


@pytest.mark.parametrize("comando", [
    "cat data/ao_vivo/ordens/2026-11-09.jsonl",
    "tail -5 data/ao_vivo/ordens/x.jsonl",
    "Get-Content data\\ao_vivo\\ordens\\x.jsonl -Tail 5",
    "ls data/ao_vivo/ordens",
    "rm data/ao_vivo_backup.txt",
    "python -c \"print(open('data/ao_vivo/ordens/x.jsonl').read())\"",
])
def test_guarda_libera_ler_o_diario(comando):
    assert guard.decide("Bash", {"command": comando}, is_open=FECHADO) is None, comando


@pytest.mark.parametrize("ferramenta", ["Edit", "Write", "NotebookEdit"])
def test_guarda_recusa_editar_o_diario_pela_ferramenta(ferramenta):
    for caminho in ("C:\\x\\data\\ao_vivo\\ordens\\2026-11-09.jsonl", "data/ao_vivo/ordens/retrato.json"):
        assert guard.decide(ferramenta, {"file_path": caminho}, is_open=FECHADO)


def test_guarda_nao_julga_script_pelo_texto():
    # Saiu a pedido do usuário (09/11/2026): procurar nomes do MT5 no texto barrava análise só de leitura.
    fora = str(Path("C:/Temp/claude/scratch/analise.py"))
    for texto in ("mt5.order_send(req)", "import MetaTrader5", "from core import ordens"):
        assert guard.decide("Write", {"file_path": fora, "content": texto}, is_open=FECHADO) is None


# Formas comuns de escapar que a revisão achou na primeira versão da trava.
@pytest.mark.parametrize("comando", [
    "py ordens_real.py", "py -3 captura.py", ".venv/Scripts/pythonw.exe ordens_real.py", "python -m ordens_real",
    ".venv/Scripts/python.exe -X utf8 captura.py", "python -W ignore ordens_real.py",
    "Start-Process python ordens_real.py", "Start-Process .venv\\Scripts\\python.exe -ArgumentList ordens_real.py",
    "cmd /c start iniciar.bat", "cmd /c iniciar", "Invoke-Item iniciar.bat",
])
def test_guarda_recusa_outras_formas_de_operar(comando):
    assert guard.decide("PowerShell", {"command": comando}, is_open=FECHADO), comando


@pytest.mark.parametrize("comando", [
    "Remove-Item data\\ao_vivo\\* -Recurse -Force", "rm -rf data/ao_vivo/*",
    "Get-ChildItem data\\ao_vivo\\ordens -Filter *.jsonl | Remove-Item", "cd data/ao_vivo/ordens; rm *.jsonl",
    "cp vazio.jsonl data/ao_vivo/ordens/x.jsonl", "Copy-Item vazio.jsonl data\\ao_vivo\\ordens\\x.jsonl -Force",
    "New-Item -Force data\\ao_vivo\\ordens\\x.jsonl", "sed -i '$d' data/ao_vivo/ordens/x.jsonl",
    "git clean -fdx", "git clean -fX",
])
def test_guarda_recusa_outras_formas_de_apagar_o_diario(comando):
    assert guard.decide("PowerShell", {"command": comando}, is_open=FECHADO), comando


@pytest.mark.parametrize("comando", [
    "python -c \"print(open('data/ao_vivo/ordens/x.jsonl').read().replace(',', ';'))\"",
    "python -c \"open('data/ao_vivo/ordens/x.jsonl', encoding='ascii').read()\"",
    "git clean -n", "git diff -- iniciar.bat", "rg captura docs/",
])
def test_guarda_nao_trava_leitura_que_parece_escrita(comando):
    assert guard.decide("PowerShell", {"command": comando}, is_open=FECHADO) is None, comando


def test_guarda_recusa_script_avulso_que_apaga_o_diario():
    conteudo = "import os; os.remove('data/ao_vivo/ordens/x.jsonl')"
    assert guard.decide("Write", {"file_path": "C:/Temp/s/x.py", "content": conteudo}, is_open=FECHADO)
    assert guard.decide("Write", {"file_path": "C:/Temp/s/x.sh", "content": conteudo}, is_open=FECHADO)


def test_guarda_olha_multiedit_e_comando_vazio():
    assert guard.decide("MultiEdit", {"file_path": "data/ao_vivo/ordens/x.jsonl", "edits": []})
    assert guard.decide("MultiEdit", {"file_path": "C:/Temp/x.py", "edits": [{"new_string": "order_send(r)"}]}) is None
    assert guard.decide("Bash", {"command": None}, is_open=FECHADO) is None


def test_guarda_nao_recusa_outras_ferramentas():
    assert guard.decide("Edit", {"file_path": "a.py"}, is_open=ABERTO) is None


# check_changes (scripts/check_changes.py)

check_changes = _modulo(RAIZ / "scripts" / "check_changes.py")


def test_check_changes_motor_e_estrategia():
    plano = check_changes.what_to_check(["core/engine/kernel.py"])
    assert any("test_motor_camadas" in c for c in plano["run"])
    assert not any("resign_code_hash" in c for c in plano["remind"])
    assert any("resign_code_hash" in c for c in check_changes.what_to_check(["strategies/x.py"])["remind"])


@pytest.mark.parametrize("arquivo,trecho", [
    ("ui/callbacks_ordens.py", "test_callbacks_sem_ciclo"),
    ("ui/components/portfolio_panel.py", "screens_reference"),
    ("ui/cb_pesquisa/r_wfa.py", "screens_reference"),
    ("ui/cb_pesquisa/r_menu.py", "test_callbacks_sem_ciclo"),
    ("ui/cb_operacao/ordens.py", "test_callbacks_sem_ciclo"),
])
def test_check_changes_tela(arquivo, trecho):
    assert any(trecho in c for c in check_changes.what_to_check([arquivo])["run"])


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
def test_check_changes_diz_o_que_reabrir(arquivo, janela):
    reabrir = check_changes.what_to_check([arquivo])["reopen"]
    assert len(reabrir) == 1 and janela in reabrir[0]


def test_check_changes_doc_nao_pede_nada():
    assert not any(check_changes.what_to_check(["docs/x.md", "AGENTS.md"]).values())
