"""Diário de ordens: arquivo primeiro, banco depois (spec §7.2)."""
from datetime import date, datetime, timedelta

import pytest

from core import db_manager as db
from core import diario_ordens
from core.diario_ordens import Diario, espelhar_pendentes

DIA = date(2026, 10, 9)
T = datetime(2026, 10, 9, 10, 1)
Q = datetime(2026, 10, 9, 10, 1, 1)


def test_registra_no_arquivo_e_relendo_o_estado_volta(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T, lado=1, contratos=2)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=1001, preco=189_010)
    novo = Diario(tmp_path, DIA)                 # a captura reabriu
    assert novo.enviada(4, T) and novo.ticket(4, T) == 1001
    assert novo.tentativas(4, T) == 1
    assert not novo.enviada(4, datetime(2026, 10, 9, 10, 2))


def test_linha_cortada_por_queda_e_ignorada_e_a_seguinte_nao_se_mistura(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    with open(d.arquivo, "a", encoding="utf-8") as f:
        f.write('{"evento_id": "x", "tipo": "execu')     # queda no meio
    d2 = Diario(tmp_path, DIA)
    d2.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=7)
    d3 = Diario(tmp_path, DIA)
    assert [e["tipo"] for e in d3.eventos] == ["enviando", "executada"]
    assert d3.ticket(4, T) == 7


def test_tipo_desconhecido_recusa(tmp_path):
    with pytest.raises(ValueError):
        Diario(tmp_path, DIA).registrar("inventado", quando=Q)


def test_tipos_novos_da_protecao_e_da_incerteza_existem():
    assert {"protecao_enviando", "incerta"} <= diario_ordens.TIPOS


def test_espelho_no_banco_nao_duplica(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T, lado=1, contratos=2,
                extra="vai para dados")
    d.registrar("conta_travada", quando=Q, conta_id=2, motivo="90% do limite")
    with db.connect_write() as con:
        db.init_schema(con)
        assert d.espelhar(con) == 2
        assert Diario(tmp_path, DIA).espelhar(con) == 0
        r = con.execute("SELECT tipo, ligacao_id, entry_ts, dados FROM ordens_eventos "
                        "ORDER BY evento_id").fetchall()
    assert r[0][0] == "enviando" and r[0][1] == 4 and r[0][2] == T
    assert "vai para dados" in r[0][3]


def test_travada_e_saida_desde(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.travada(2) is None
    d.registrar("conta_travada", quando=Q, conta_id=2, motivo="90%")
    assert d.travada(2)["motivo"] == "90%"
    d.registrar("saida_enviando", quando=Q, ligacao_id=4, ticket=55)
    d.registrar("saida_recusada", quando=datetime(2026, 10, 9, 10, 1, 3), ligacao_id=4, ticket=55)
    assert d.saida_desde(55) == Q
    d.registrar("saida_executada", quando=datetime(2026, 10, 9, 10, 1, 5), ligacao_id=4, ticket=55)
    assert d.saida_desde(55) is None


def test_ticket_devolve_o_ultimo_e_none_sem_ticket(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.ticket(4, T) is None
    d.registrar("parcial", quando=Q, ligacao_id=4, entry_ts=T, ticket=11)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=22)
    assert d.ticket(4, T) == 22
    assert Diario(tmp_path, DIA).ticket(4, T) == 22


def test_registrado_e_ultimo_motivo(tmp_path):
    d = Diario(tmp_path, DIA)
    assert not d.registrado(4, T, "recusada") and d.ultimo_motivo(4, T) is None
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("recusada", quando=Q, ligacao_id=4, entry_ts=T, motivo="sem margem")
    d.registrar("nao_entrou", quando=Q, ligacao_id=4, entry_ts=T, motivo="passou da janela")
    assert d.registrado(4, T, "recusada") and not d.registrado(4, T, "perdida")
    assert d.ultimo_motivo(4, T) == "passou da janela"
    assert d.ultimo_motivo(5, T) is None


def test_ultimo_devolve_o_evento_mais_recente_da_operacao(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.ultimo(4, T) is None
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=9)
    d.registrar("enviando", quando=Q, ligacao_id=5, entry_ts=T)
    assert d.ultimo(4, T)["tipo"] == "executada"
    assert d.ultimo(5, T)["tipo"] == "enviando"


def test_ultima_tentativa_filtra_por_tipo_ticket_e_operacao(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.ultima_tentativa("enviando", lig=4, entry_ts=T) is None
    q2, q3 = Q + timedelta(seconds=2), Q + timedelta(seconds=5)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("enviando", quando=q2, ligacao_id=4, entry_ts=T)
    d.registrar("enviando", quando=q3, ligacao_id=5, entry_ts=T)
    d.registrar("saida_enviando", quando=Q, ligacao_id=4, ticket=55)
    d.registrar("saida_enviando", quando=q3, ligacao_id=4, ticket=66)
    assert d.ultima_tentativa("enviando", lig=4, entry_ts=T) == q2
    assert d.ultima_tentativa("enviando", lig=5, entry_ts=T) == q3
    assert d.ultima_tentativa("enviando", lig=4, entry_ts=datetime(2026, 10, 9, 11)) is None
    assert d.ultima_tentativa("saida_enviando", ticket=55) == Q
    assert d.ultima_tentativa("saida_enviando", ticket=66) == q3
    assert d.ultima_tentativa("protecao_enviando", ticket=55) is None


def test_executada_em_e_a_primeira_execucao(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.executada_em(4, T) is None
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("parcial", quando=Q + timedelta(seconds=1), ligacao_id=4, entry_ts=T, ticket=3)
    d.registrar("executada", quando=Q + timedelta(seconds=2), ligacao_id=4, entry_ts=T, ticket=3)
    assert d.executada_em(4, T) == Q + timedelta(seconds=1)


def test_tickets_abertos_tira_os_que_ja_sairam(tmp_path):
    d = Diario(tmp_path, DIA)
    t2 = datetime(2026, 10, 9, 10, 5)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=100)
    d.registrar("adotada", quando=Q, ligacao_id=4, entry_ts=t2, ticket=200)
    d.registrar("executada", quando=Q, ligacao_id=9, entry_ts=T, ticket=300)
    assert sorted(d.tickets_abertos(4)) == [(100, T), (200, t2)]
    d.registrar("saida_executada", quando=Q, ligacao_id=4, ticket=100)
    assert d.tickets_abertos(4) == [(200, t2)]
    d.registrar("saiu_antes", quando=Q, ligacao_id=4, ticket=200)
    assert d.tickets_abertos(4) == []
    assert d.tickets_abertos(9) == [(300, T)]


def test_comandos_do_dia_filtra_pelo_nome_do_comando(tmp_path):
    d = Diario(tmp_path, DIA)
    assert d.comandos_do_dia("pausar") == []
    d.registrar("comando", quando=Q, motivo="pausar", conta_id=1)
    d.registrar("comando", quando=Q, motivo="destravar", conta_id=1)
    d.registrar("comando", quando=Q, motivo="pausar", conta_id=2)
    d.registrar("recusada", quando=Q, motivo="pausar")
    r = d.comandos_do_dia("pausar")
    assert [e["conta_id"] for e in r] == [1, 2]
    assert all(e["tipo"] == "comando" for e in r)


def test_pasta_padrao_e_desviada_pelo_conftest(tmp_path):
    assert diario_ordens.PASTA == tmp_path / "ao_vivo" / "ordens"
    assert diario_ordens.PASTA != db.DATA / "ao_vivo" / "ordens"


def test_espelhar_pendentes_pega_so_os_ultimos_dias(tmp_path):
    pasta = tmp_path / "ordens"
    hoje = date(2026, 10, 9)
    for dia, n in ((hoje, 2), (hoje - timedelta(days=4), 1), (hoje - timedelta(days=5), 1),
                   (hoje - timedelta(days=30), 3)):
        d = Diario(pasta, dia)
        for _ in range(n):
            d.registrar("seria_enviada", quando=datetime(dia.year, dia.month, dia.day, 10))
    (pasta / "lixo.jsonl").write_text("{}\n", encoding="utf-8")
    with db.connect_write() as con:
        db.init_schema(con)
        # janela de 5 dias contados de `hoje`: entram hoje e hoje-4
        assert espelhar_pendentes(pasta, con, dias=5, hoje=hoje) == 3
        assert espelhar_pendentes(pasta, con, dias=5, hoje=hoje) == 0
        assert con.execute("SELECT count(*) FROM ordens_eventos").fetchone()[0] == 3
        assert espelhar_pendentes(pasta, con, dias=60, hoje=hoje) == 4
    assert espelhar_pendentes(tmp_path / "nao_existe", None) == 0


def test_linha_do_meio_pulada_nao_repete_id(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=1)
    d.registrar("saida_enviando", quando=Q, ligacao_id=4, ticket=1)
    linhas = d.arquivo.read_text(encoding="utf-8").split("\n")
    linhas[1] = '{"evento_id": "lixo'                       # corrompe a do meio
    d.arquivo.write_text("\n".join(linhas), encoding="utf-8")
    d2 = Diario(tmp_path, DIA)
    d2.registrar("saida_executada", quando=Q, ligacao_id=4, ticket=1)
    ids = [e["evento_id"] for e in Diario(tmp_path, DIA).eventos]
    assert len(ids) == 3 and len(set(ids)) == 3
    assert ids[-1].endswith("-000004")


def test_motivo_com_separador_unicode_volta_inteiro(tmp_path):
    d = Diario(tmp_path, DIA)
    motivo = "linha um linha dois\x0bfim"
    d.registrar("recusada", quando=Q, ligacao_id=4, entry_ts=T, motivo=motivo)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    novo = Diario(tmp_path, DIA)
    assert [e["tipo"] for e in novo.eventos] == ["recusada", "enviando"]
    assert novo.eventos[0]["motivo"] == motivo


def test_linha_que_nao_e_evento_e_ignorada(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    with open(d.arquivo, "a", encoding="utf-8") as f:
        f.write("123\n[1, 2]\n{\"sem\": \"tipo\"}\n")
    novo = Diario(tmp_path, DIA)
    assert [e["tipo"] for e in novo.eventos] == ["enviando"]
    assert novo.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T,
                          ticket=3)["evento_id"].endswith("-000005")


def test_linha_ruim_nao_impede_o_espelho_das_outras(tmp_path):
    d = Diario(tmp_path, DIA)
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket="abc")
    d.registrar("saida_enviando", quando=Q, ligacao_id=4, ticket=5)
    with db.connect_write() as con:
        db.init_schema(con)
        assert d.espelhar(con) == 2
        assert espelhar_pendentes(tmp_path, con, dias=5, hoje=DIA) == 0
        tipos = [r[0] for r in con.execute(
            "SELECT tipo FROM ordens_eventos ORDER BY evento_id").fetchall()]
    assert tipos == ["enviando", "saida_enviando"]


def test_desfecho_e_tentativa_sem_desfecho():
    import tempfile
    d = Diario(tempfile.mkdtemp(), DIA)
    assert d.desfecho(4, T) is None and d.tentativa_sem_desfecho(4, T) is None
    d.registrar("enviando", quando=Q, ligacao_id=4, entry_ts=T)
    d.registrar("chamado", quando=Q + timedelta(seconds=1), ligacao_id=4, entry_ts=T)
    assert d.tentativa_sem_desfecho(4, T) == Q and d.desfecho(4, T) is None
    d.registrar("incerta", quando=Q + timedelta(seconds=2), ligacao_id=4, entry_ts=T)
    assert d.tentativa_sem_desfecho(4, T) == Q + timedelta(seconds=2)
    d.registrar("aceita", quando=Q + timedelta(seconds=3), ligacao_id=4, entry_ts=T)
    assert d.desfecho(4, T) == "aceita" and d.tentativa_sem_desfecho(4, T) is None
    d.registrar("enviando", quando=Q + timedelta(seconds=9), ligacao_id=4, entry_ts=T)
    assert d.desfecho(4, T) is None     # nova tentativa: o desfecho antigo não vale


def test_protecao_pendente_desde_e_registrada():
    import tempfile
    d = Diario(tempfile.mkdtemp(), DIA)
    d.registrar("executada", quando=Q, ligacao_id=4, entry_ts=T, ticket=7, lado=-1,
                stop_px=100, alvo_px=90)
    assert d.protecao_registrada(7) == (-1, 100, 90) and d.protecao_registrada(8) is None
    assert d.protecao_pendente_desde(7) is None
    d.registrar("protecao_enviando", quando=Q, ticket=7, ligacao_id=4)
    d.registrar("protecao_enviando", quando=Q + timedelta(seconds=1), ticket=7)
    assert d.protecao_pendente_desde(7) == Q
    d.registrar("protecao", quando=Q + timedelta(seconds=2), ticket=7, stop_px=99,
                alvo_px=90)
    assert d.protecao_pendente_desde(7) is None
    assert d.protecao_registrada(7) == (-1, 99, 90)
    assert d.ligacoes_abertas() == {4}


def test_espelho_grava_a_origem_do_evento_e_nao_mistura(tmp_path):
    # pastas separadas, como na produção (demo e real nunca dividem o arquivo)
    pasta_demo, pasta_real = tmp_path / "demo", tmp_path / "real"
    Diario(pasta_demo, DIA).registrar("seria_enviada", quando=Q, ligacao_id=5)
    Diario(pasta_real, DIA, "real").registrar("enviando", quando=Q, ligacao_id=6,
                                              entry_ts=T, lado=1, contratos=1)
    with db.connect_write() as con:
        db.init_schema(con)
        assert Diario(pasta_demo, DIA).espelhar(con) == 1
        assert Diario(pasta_real, DIA, "real").espelhar(con) == 1
        r = con.execute("SELECT evento_id, origem, ligacao_id FROM ordens_eventos "
                        "ORDER BY evento_id").fetchall()
    assert [(e.partition("-")[0], o) for e, o, _ in r] == [("demo", "demo"),
                                                           ("real", "real")]
    assert {lig for _, _, lig in r} == {5, 6}


def test_espelhar_pendentes_aceita_lista_de_pastas(tmp_path):
    pasta_demo, pasta_real = tmp_path / "demo", tmp_path / "real"
    Diario(pasta_demo, DIA).registrar("seria_enviada", quando=Q)
    Diario(pasta_real, DIA, "real").registrar("seria_enviada", quando=Q)
    with db.connect_write() as con:
        db.init_schema(con)
        assert espelhar_pendentes([pasta_demo, pasta_real], con, dias=5, hoje=DIA) == 2
        assert espelhar_pendentes([pasta_demo, pasta_real], con, dias=5, hoje=DIA) == 0
        origens = con.execute("SELECT origem FROM ordens_eventos ORDER BY origem"
                              ).fetchall()
    assert origens == [("demo",), ("real",)]
