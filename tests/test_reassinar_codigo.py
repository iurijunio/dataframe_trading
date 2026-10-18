"""O comando de reassinar de ponta a ponta, num banco de teste: o backtest
do plano com o código antigo e com o novo, cada um no seu processo, e só o
plano com trades idênticos ganha o hash novo."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import codigo  # noqa: E402
from core import db_manager as db  # noqa: E402
from core import plano as _plano  # noqa: E402
from strategies import registry  # noqa: E402
from tests._cadeia import banco, campos_plano  # noqa: E402,F401

_spec = importlib.util.spec_from_file_location(
    "reassinar_codigo", RAIZ / "scripts" / "reassinar_codigo.py")
reassinar_codigo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reassinar_codigo)


def _codigo_antigo(destino: Path) -> Path:
    """Cópia do código de hoje com base.py mexido só num comentário (hash
    novo, mesmos trades) e o cruzamento com as entradas trocadas (hash novo,
    trades diferentes)."""
    for pasta in ("core", "strategies", "configs"):
        shutil.copytree(RAIZ / pasta, destino / pasta,
                        ignore=shutil.ignore_patterns("__pycache__"))
    base = destino / "strategies" / "base.py"
    base.write_text(base.read_text(encoding="utf-8") + "\n# versão antiga\n",
                    encoding="utf-8")
    cruz = destino / "strategies" / "setup_cruzamento.py"
    texto = cruz.read_text(encoding="utf-8")
    assert "entry_long=cruza_cima" in texto and "entry_short=cruza_baixo" in texto
    cruz.write_text(texto.replace("entry_long=cruza_cima", "entry_long=X")
                    .replace("entry_short=cruza_baixo", "entry_short=cruza_cima")
                    .replace("entry_long=X", "entry_long=cruza_baixo"),
                    encoding="utf-8")
    return destino


def _padrao(estrategia):
    return {k: v["default"]
            for k, v in registry.definir(estrategia).params_schema.items()}


def test_reassina_so_o_plano_com_trades_identicos(banco, tmp_path):
    antigo = _codigo_antigo(tmp_path / "antigo")
    pasta_antiga = antigo / "strategies"
    h_canal = codigo.hash_estrategia("rompimento_canal", pasta_antiga)
    h_cruz = codigo.hash_estrategia("setup_cruzamento", pasta_antiga)
    assert h_canal != codigo.hash_estrategia("rompimento_canal")

    with db.connect_write() as con:
        # barras reais do espelho (só leitura), meio ano
        fonte = (db.PARQUET_DIR / db.safe_symbol("WIN$N")).as_posix()
        con.execute(
            "INSERT INTO bars_m1 SELECT 'WIN$N', ts, open, high, low, close, "
            "tick_volume, volume, 0, 0 FROM read_parquet("
            f"{db._sql_str(fonte + '/**/*.parquet')}) "
            "WHERE ts BETWEEN '2025-01-01' AND '2025-06-30 23:59'")
    canal = _plano.salvar(**campos_plano(
        strategy="rompimento_canal", wfa_id=1, codigo_hash=h_canal,
        params=_padrao("rompimento_canal")))
    cruz = _plano.salvar(**campos_plano(
        strategy="setup_cruzamento", wfa_id=2, codigo_hash=h_cruz,
        params=_padrao("setup_cruzamento")))
    with db.connect_write() as con:
        for lig, pid, h in [(1, canal, h_canal), (2, cruz, h_cruz)]:
            con.execute("INSERT INTO papel_pregoes (ligacao_id, dia, "
                        "plano_id, codigo_hash, status) VALUES "
                        "(?, '2025-06-30', ?, ?, 'conferido')", [lig, pid, h])

    rel = reassinar_codigo.executar(
        pasta_antiga=antigo, aplicar=True, banco=db.DB_PATH,
        backup=tmp_path / "backup", trabalho=tmp_path / "trabalho")

    por_plano = {p["plano_id"]: p for p in rel["planos"]}
    assert por_plano[canal]["identicos"] is True
    assert por_plano[canal]["n_trades_fechado"] > 0
    assert por_plano[cruz]["identicos"] is False
    assert por_plano[cruz]["diferenca"]
    # o trabalhador rodou mesmo o código de cada pasta
    assert por_plano[canal]["arquivo_antigo"].startswith(str(antigo))
    assert por_plano[canal]["arquivo_novo"].startswith(str(RAIZ))

    novo_canal = codigo.hash_estrategia("rompimento_canal")
    with db.connect(read_only=True) as con:
        assert dict(con.execute("SELECT plano_id, codigo_hash "
                                "FROM planos_operacao").fetchall()) == {
            canal: novo_canal, cruz: h_cruz}
        assert dict(con.execute("SELECT plano_id, codigo_hash "
                                "FROM papel_pregoes").fetchall()) == {
            canal: novo_canal, cruz: h_cruz}
    assert rel["alterado"] == [{"plano_id": canal, "hash_antigo": h_canal,
                                "hash_novo": novo_canal, "planos": 1,
                                "pregoes": 1}]
    assert (tmp_path / "backup" / "database.duckdb").exists()
    assert Path(rel["log"]).exists()


def test_sem_trades_nao_reassina_e_sem_aplicar_nao_grava(banco, tmp_path):
    antigo = _codigo_antigo(tmp_path / "antigo")
    h = codigo.hash_estrategia("rompimento_canal", antigo / "strategies")
    pid = _plano.salvar(**campos_plano(codigo_hash=h,
                                       params=_padrao("rompimento_canal")))
    for aplicar in (False, True):
        # banco sem barras: zero trades dos dois lados não prova nada
        rel = reassinar_codigo.executar(
            pasta_antiga=antigo, banco=db.DB_PATH, aplicar=aplicar,
            backup=tmp_path / "backup", trabalho=tmp_path / f"t{aplicar}")
        assert rel["alterado"] == []
        assert rel["planos"][0]["plano_id"] == pid
        assert rel["planos"][0]["identicos"] is False
    assert not (tmp_path / "backup").exists()
    with db.connect(read_only=True) as con:
        assert con.execute("SELECT codigo_hash FROM planos_operacao "
                           "WHERE plano_id = ?", [pid]).fetchone()[0] == h
