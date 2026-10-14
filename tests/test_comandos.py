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
