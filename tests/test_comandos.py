"""Comandos da tela para a captura, por arquivo (spec §3, §5.8)."""
import pytest

from core import comandos


def test_escreve_e_consome_em_ordem_e_apaga(tmp_path):
    comandos.escrever(tmp_path, "zerar_tudo")
    comandos.escrever(tmp_path, "encerrar_posicao", ticket=55)
    lidos = comandos.consumir(tmp_path)
    assert [c["tipo"] for c in lidos] == ["zerar_tudo", "encerrar_posicao"]
    assert lidos[1]["ticket"] == 55 and comandos.consumir(tmp_path) == []
    assert not list(tmp_path.iterdir())


def test_tipo_desconhecido_recusa(tmp_path):
    with pytest.raises(ValueError):
        comandos.escrever(tmp_path, "inventado")
    assert not list(tmp_path.iterdir())


def test_arquivo_temporario_nao_e_consumido(tmp_path):
    (tmp_path / "x.json.tmp").write_text("{}")
    assert comandos.consumir(tmp_path) == []
    assert (tmp_path / "x.json.tmp").exists()


def test_pasta_inexistente_devolve_vazio(tmp_path):
    assert comandos.consumir(tmp_path / "nada") == []


def test_registrar_vem_antes_de_apagar(tmp_path):
    # o diário recebe o comando ANTES de o arquivo sumir: uma queda no meio
    # deixa o arquivo (lido de novo), nunca um comando perdido
    comandos.escrever(tmp_path, "zerar_tudo")
    vistos = []

    def registrar(c):
        vistos.append(len(list(tmp_path.glob("*.json"))))
    comandos.consumir(tmp_path, registrar=registrar)
    assert vistos == [1] and not list(tmp_path.glob("*.json"))


def test_registro_que_falha_deixa_o_arquivo(tmp_path):
    comandos.escrever(tmp_path, "zerar_tudo")

    def quebra(c):
        raise OSError("disco cheio")
    with pytest.raises(OSError):
        comandos.consumir(tmp_path, registrar=quebra)
    assert [c["tipo"] for c in comandos.consumir(tmp_path)] == ["zerar_tudo"]


def test_arquivo_ilegivel_e_descartado_sem_travar_os_outros(tmp_path):
    (tmp_path / "00000000000000000000-lixo.json").write_text("{nao json")
    comandos.escrever(tmp_path, "zerar_tudo")
    assert [c["tipo"] for c in comandos.consumir(tmp_path)] == ["zerar_tudo"]
    assert not list(tmp_path.iterdir())


def test_conftest_desvia_a_pasta_real(tmp_path):
    assert str(comandos.PASTA).startswith(str(tmp_path))


def test_conftest_desvia_a_pasta_real_da_conta_real(tmp_path):
    # a pasta da conta real nunca pode ser a do usuário durante um teste
    assert str(comandos.PASTA_REAL).startswith(str(tmp_path))
    assert comandos.PASTA_REAL != comandos.PASTA


def test_pasta_do_tipo_roteia_demo_e_real(tmp_path, monkeypatch):
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "demo")
    monkeypatch.setattr(comandos, "PASTA_REAL", tmp_path / "real")
    assert comandos.pasta_do_tipo("demo") == tmp_path / "demo"
    assert comandos.pasta_do_tipo("real") == tmp_path / "real"


def test_pasta_do_tipo_le_a_constante_na_hora(tmp_path, monkeypatch):
    # o conftest desvia as pastas depois do import: nada pode ficar preso
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "outra")
    assert comandos.pasta_do_tipo("demo") == tmp_path / "outra"


def test_pasta_do_tipo_desconhecido_recusa():
    with pytest.raises(ValueError):
        comandos.pasta_do_tipo("mesa")


def test_zerar_tudo_grava_nas_duas_pastas_sem_tocar_no_banco(tmp_path, monkeypatch):
    monkeypatch.setattr(comandos, "PASTA", tmp_path / "demo")
    monkeypatch.setattr(comandos, "PASTA_REAL", tmp_path / "real")

    def explode(*a, **k):
        raise AssertionError("zerar não pode tocar no banco")
    monkeypatch.setattr(comandos.db, "connect", explode)
    monkeypatch.setattr(comandos.db, "connect_write", explode)
    ids = comandos.escrever_zerar_tudo()
    assert len(ids) == 2
    for pasta in (tmp_path / "demo", tmp_path / "real"):
        [cmd] = comandos.consumir(pasta)
        assert cmd["tipo"] == "zerar_tudo"
