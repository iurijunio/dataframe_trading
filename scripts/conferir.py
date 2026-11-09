"""Diz o que conferir e o que reabrir depois de mudar código.

    .venv/Scripts/python.exe scripts/conferir.py                # o que mudou e não foi commitado
    .venv/Scripts/python.exe scripts/conferir.py --de <commit>  # desde um commit
    .venv/Scripts/python.exe scripts/conferir.py --rodar        # roda também as conferências

As listas ficam aqui para a regra não depender de memória. Só conferências que
não precisam de argumento rodam com --rodar; as outras saem como lembrete.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = str(Path(".venv/Scripts/python.exe"))

CICLO = re.compile(r"ui/(app\.py|callbacks.*\.py|cb_\w+/\w+\.py)$")
MOTOR = re.compile(r"(core/engine/|strategies/)")
ESTRATEGIA = re.compile(r"(strategies/|core/codigo\.py$)")
BUSCA = re.compile(r"(busca\.py$|core/busca/)")
MENU = re.compile(r"ui/components/(controls|mining|mine_\w+|catalogo)\.py$")
TELA_PESQUISA = re.compile(
    r"ui/(callbacks\.py|cb_pesquisa/\w+\.py|callbacks_(candidata|portfolio)\.py|components/(mining|mine_\w+|scatter|charts|stats_cards|"
    r"results_grid|wfa_\w+|candidata_panel|portfolio_panel|detalhes_cards|robustez_cards|analytics_charts|cartao|ficha)\.py)$"
)
TEM_CODIGO = re.compile(r"\.(py|sql|js|css)$")
FECHA_CAPTURA = re.compile(
    r"(^captura\.py$|core/(captura|ingest|db_manager|papel|plano|variantes|mt5_source|contrato_dia|conferencia_ordens|ordens_backtest)\.py$|core/schema\.sql$|core/engine/|strategies/)"
)
FECHA_AS_DUAS = re.compile(r"(^ordens_real\.py$|core/(ordens|corretora|papel_vivo|ponte|comandos|diario_ordens|ordem_teste|contrato_dia|captura|db_manager)\.py$)")


def o_que_conferir(arquivos: list[str]) -> dict[str, list[str]]:
    """Traduz os arquivos mudados em conferências e reaberturas."""
    arquivos = [a.replace("\\", "/") for a in arquivos]
    tem = lambda regra: any(regra.search(a) for a in arquivos)  # noqa: E731
    rodar: list[str] = []
    lembrar: list[str] = []
    if tem(TEM_CODIGO):
        lembrar.append("Suíte inteira: pytest -q")
    if tem(CICLO):
        rodar.append(f"{PY} -m pytest -q tests/test_callbacks_sem_ciclo.py")
    if tem(MOTOR):
        rodar.append(f"{PY} scripts/gabarito_motor.py conferir")
        lembrar.append("Foto do WIN antes e depois, tem de dar idêntico: scripts/foto_win.py gravar / conferir")
    if tem(ESTRATEGIA):
        lembrar.append("Mudou o código da estratégia: scripts/reassinar_codigo.py --de <commit> (fora do pregão)")
    if tem(BUSCA):
        lembrar.append("Prova da busca: scripts/conferir_busca.py <busca_id>. Busca em andamento segue com o código antigo")
    if tem(MENU):
        rodar.append(f"{PY} scripts/campos_menu.py conferir")
    if tem(TELA_PESQUISA):
        rodar.append(f"{PY} scripts/referencia_telas.py conferir")
    reabrir: list[str] = []
    if tem(FECHA_AS_DUAS):
        reabrir.append("Feche as janelas Dataframe - Captura e Dataframe - Ordens real, depois abra o iniciar.bat")
    elif tem(FECHA_CAPTURA):
        reabrir.append("Feche a janela Dataframe - Captura, depois abra o iniciar.bat")
    elif any(a.startswith(("ui/", "core/")) for a in arquivos):
        reabrir.append("Feche e abra o iniciar.bat")
    return {"rodar": rodar, "lembrar": lembrar, "reabrir": reabrir}


def _git(*args: str) -> list[str]:
    saida = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    return [s for s in saida.splitlines() if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", default="HEAD", help="comparar desde este commit")
    ap.add_argument("--rodar", action="store_true", help="rodar as conferências sem argumento")
    args = ap.parse_args()
    arquivos = _git("diff", "--name-only", args.de) + _git("ls-files", "--others", "--exclude-standard")
    plano = o_que_conferir(arquivos)
    for titulo, chave in (("Conferir", "rodar"), ("Lembrar", "lembrar"), ("Reabrir", "reabrir")):
        for item in plano[chave]:
            print(f"{titulo}: {item}")
    if not any(plano.values()):
        print("Nada a conferir.")
    falhou = 0
    if args.rodar:
        for comando in plano["rodar"]:
            print(f"\n>>> {comando}")
            falhou += subprocess.run(comando.split(), cwd=RAIZ).returncode != 0
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
