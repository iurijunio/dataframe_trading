"""Testes da sincronização automática com o MT5 (projeto B).

O que estes testes protegem: o TSV que `exportar_tsv` escreve precisa ser
exatamente o que `core.ingest.read_mt5_export` — já testado e usado pela
importação manual — sabe ler de volta, sem nenhuma lógica de merge nova
aqui.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db  # noqa: E402
from core import ingest as ing  # noqa: E402
from core import mt5_source as src  # noqa: E402


def _barras():
    return pl.DataFrame({
        "ts": [datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 9, 1)],
        "open": [100000, 100050],
        "high": [100100, 100120],
        "low": [99950, 100000],
        "close": [100050, 100080],
        "tick_volume": [120, 95],
        "volume": [0, 0],
        "spread": [5, 5],
    })


def test_exportar_tsv_e_read_mt5_export_fazem_roundtrip(tmp_path):
    """O que `exportar_tsv` escreve, `ing.read_mt5_export` precisa
    conseguir ler de volta, com os mesmos valores — senão a sincronização
    grava um arquivo que a ingestão existente rejeita."""
    destino = tmp_path / "mt5_sync_teste.tsv"
    barras = _barras()

    src.exportar_tsv(barras, destino)
    lido = ing.read_mt5_export(destino, price_decimals=0)

    assert lido["ts"].to_list() == barras["ts"].to_list()
    assert lido["open"].to_list() == barras["open"].to_list()
    assert lido["high"].to_list() == barras["high"].to_list()
    assert lido["low"].to_list() == barras["low"].to_list()
    assert lido["close"].to_list() == barras["close"].to_list()
    assert lido["tick_volume"].to_list() == barras["tick_volume"].to_list()
    assert lido["volume"].to_list() == barras["volume"].to_list()
    assert lido["spread"].to_list() == barras["spread"].to_list()


def test_exportar_tsv_cria_a_pasta_se_nao_existir(tmp_path):
    destino = tmp_path / "sub" / "pasta" / "mt5_sync_teste.tsv"
    src.exportar_tsv(_barras(), destino)
    assert destino.exists()


def test_exportar_tsv_recusa_coluna_faltando(tmp_path):
    """Sem checagem explícita, faltar 'spread' vira um KeyError cru dentro
    do laço — a mensagem precisa dizer qual coluna falta, no mesmo estilo
    de ing.read_mt5_export."""
    barras = _barras().drop("spread")
    with pytest.raises(ValueError, match="spread"):
        src.exportar_tsv(barras, tmp_path / "sem_coluna.tsv")


def test_exportar_tsv_recusa_valor_nulo(tmp_path):
    """Um None gravado como texto ('None') no TSV quebraria read_mt5_export
    de um jeito confuso lá na frente — recusa aqui, com motivo."""
    barras = _barras().with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(None).otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(ValueError, match="nulo"):
        src.exportar_tsv(barras, tmp_path / "com_nulo.tsv")


# ---------------------------------------------------------- offset_servidor

class _FakeTick:
    def __init__(self, epoch):
        self.time = epoch


class _FakeMT5Offset:
    """Substitui o módulo MetaTrader5 nos testes de offset_servidor."""

    def __init__(self, epoch_servidor):
        self._epoch = epoch_servidor

    def symbol_info_tick(self, symbol):
        if symbol != "WIN$N":
            return None
        return _FakeTick(self._epoch)


def _instalar_fake_mt5(monkeypatch, epoch_servidor):
    fake = _FakeMT5Offset(epoch_servidor)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake


def test_offset_servidor_calibra_fuso_de_horas_inteiras(monkeypatch):
    """Servidor 3 horas à frente do UTC (ex: fuso do corretor)."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora + timedelta(hours=3)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    offset = src.offset_servidor("WIN$N")

    assert offset == timedelta(hours=3)


def test_offset_servidor_recusa_simbolo_desconhecido(monkeypatch):
    _instalar_fake_mt5(monkeypatch, 0)
    with pytest.raises(src.MT5Error, match="não encontrado"):
        src.offset_servidor("XXX$N")


def test_offset_servidor_recusa_fuso_que_nao_e_hora_inteira(monkeypatch):
    """Se o offset não bate com nenhuma hora inteira, algo está errado na
    calibração: melhor parar do que gravar hora torta silenciosamente."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora + timedelta(hours=3, minutes=17)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    with pytest.raises(src.MT5Error, match="múltiplo de hora"):
        src.offset_servidor("WIN$N")


def test_offset_servidor_recusa_tick_parado_ha_dias(monkeypatch):
    """Um tick de 3 dias atrás (mercado fechado, terminal sem cotação nova)
    também bate 'múltiplo de hora inteira' — 72h é múltiplo de hora — e
    passaria disfarçado de fuso válido sem um limite de plausibilidade.
    Nenhum corretor real fica a mais de 14h de UTC."""
    agora = datetime.now(timezone.utc)
    epoch_servidor = int((agora - timedelta(days=3)).timestamp())
    _instalar_fake_mt5(monkeypatch, epoch_servidor)

    with pytest.raises(src.MT5Error, match="implausível"):
        src.offset_servidor("WIN$N")


# ------------------------------------------------------------ buscar_barras

class _FakeTickFresco(_FakeTick):
    """Tick sempre 'agora', para nao acionar a recusa de offset implausivel
    quando o teste nao quer testar isso."""
    def __init__(self):
        super().__init__(int(datetime.now(timezone.utc).timestamp()))


class _FakeMT5Rates:
    TIMEFRAME_M1 = 1

    def __init__(self, taxas=None, symbol_ok=True):
        self._taxas = taxas
        self._symbol_ok = symbol_ok

    def symbol_info_tick(self, symbol):
        return _FakeTickFresco()

    def symbol_select(self, symbol, enable):
        return self._symbol_ok

    def copy_rates_range(self, symbol, timeframe, desde, ate):
        return self._taxas


def _taxas_numpy():
    import numpy as np
    dtype = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
             ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4"),
             ("real_volume", "i8")]
    linhas = [
        (1758441600, 100000.0, 100100.0, 99950.0, 100050.0, 120, 5, 0),
        (1758441660, 100050.0, 100120.0, 100000.0, 100080.0, 95, 5, 0),
    ]
    return np.array(linhas, dtype=dtype)


def test_buscar_barras_converte_epoch_e_renomeia_colunas(monkeypatch):
    fake = _FakeMT5Rates(taxas=_taxas_numpy())
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    df = src.buscar_barras("WIN$N", datetime(2026, 9, 21), datetime(2026, 9, 22))

    assert list(df.columns) == ["ts", "open", "high", "low", "close",
                                 "tick_volume", "volume", "spread"]
    assert df.height == 2
    esperado = datetime.fromtimestamp(1758441600, tz=timezone.utc).replace(tzinfo=None)
    assert df["ts"][0] == esperado
    assert df["open"][0] == 100000.0
    assert df["high"][0] == 100100.0
    assert df["low"][0] == 99950.0
    assert df["close"][0] == 100050.0
    assert df["tick_volume"][0] == 120
    assert df["volume"][0] == 0  # real_volume da linha, nao spread
    assert df["spread"][0] == 5


def test_buscar_barras_recusa_simbolo_que_nao_seleciona(monkeypatch):
    fake = _FakeMT5Rates(taxas=_taxas_numpy(), symbol_ok=False)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    with pytest.raises(src.MT5Error, match="selecionar"):
        src.buscar_barras("WIN$N", datetime(2026, 9, 21), datetime(2026, 9, 22))


def test_buscar_barras_recusa_resultado_vazio(monkeypatch):
    fake = _FakeMT5Rates(taxas=None)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    with pytest.raises(src.MT5Error, match="não devolveu"):
        src.buscar_barras("WIN$N", datetime(2026, 9, 21), datetime(2026, 9, 22))


class _FakeMT5RatesComOffset(_FakeMT5Rates):
    """Servidor 3h a frente de UTC (offset != 0), pra provar a direcao da
    conta: pedido em UTC (- offset), resultado de volta em hora de
    corretor (+ offset) -- com offset zero (_FakeMT5Rates comum) as duas
    contas dao no mesmo, e um sinal trocado passaria despercebido."""

    def __init__(self, taxas):
        super().__init__(taxas=taxas)
        self.pedido = {}

    def symbol_info_tick(self, symbol):
        epoch = int(datetime.now(timezone.utc).timestamp()) + 3 * 3600
        return _FakeTick(epoch)

    def copy_rates_range(self, symbol, timeframe, desde, ate):
        self.pedido["desde"] = desde
        self.pedido["ate"] = ate
        return self._taxas


def test_buscar_barras_pede_em_utc_e_devolve_em_hora_de_corretor(monkeypatch):
    fake = _FakeMT5RatesComOffset(taxas=_taxas_numpy())
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    desde_pedido = datetime(2026, 9, 21, 9, 0)
    ate_pedido = datetime(2026, 9, 22, 9, 0)
    df = src.buscar_barras("WIN$N", desde_pedido, ate_pedido)

    # a API pediu 3h ANTES do que a tela pediu (desde/ate estao em hora de
    # corretor; a API quer UTC, e o corretor esta 3h a frente de UTC)
    assert fake.pedido["desde"] == desde_pedido - timedelta(hours=3)
    assert fake.pedido["ate"] == ate_pedido - timedelta(hours=3)

    # o epoch devolvido pela API (UTC de verdade) volta 3h A FRENTE, para
    # casar com a hora de corretor que ja esta gravada no banco
    esperado = (datetime.fromtimestamp(1758441600, tz=timezone.utc)
                .replace(tzinfo=None) + timedelta(hours=3))
    assert df["ts"][0] == esperado


# -------------------------------------------------------------- sincronizar

@pytest.fixture
def con(tmp_path):
    c = db.connect(tmp_path / "t.duckdb")
    db.init_schema(c)
    yield c
    c.close()


def test_sincronizar_recusa_sem_nenhuma_barra_salva(con, monkeypatch):
    with pytest.raises(src.MT5Error, match="não tem nenhuma barra salva"):
        src.sincronizar(con, "WIN$N", price_decimals=0)


def test_sincronizar_busca_do_ultimo_ts_com_folga_ate_agora(con, tmp_path, monkeypatch):
    # semeia uma barra existente via ingest_csv de verdade
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export  # reaproveita o helper existente
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    chamadas = {}

    def fake_buscar(symbol, desde, ate):
        chamadas["desde"] = desde
        chamadas["ate"] = ate
        return pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        })

    monkeypatch.setattr(src, "buscar_barras", fake_buscar)
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)

    resultado = src.sincronizar(con, "WIN$N", price_decimals=0)

    assert chamadas["desde"] == ts0 - timedelta(days=src.FOLGA_DIAS)
    assert resultado.ingest.rows_inserted == 1
    assert resultado.trading_days >= 1
    assert (tmp_path / "raw").exists()


def test_sincronizar_pede_ate_alem_de_agora_por_margem(con, tmp_path, monkeypatch):
    """`ate` não pode ser exatamente `datetime.now()`: essa é a hora da
    MÁQUINA local, não a hora de corretor que buscar_barras espera (mesma
    convenção do `ultimo` salvo). Em vez de calcular a hora de corretor
    certa aqui (o que exigiria offset_servidor, que sincronizar
    deliberadamente não chama), pede-se uma margem folgada além de agora —
    o MT5 nunca devolve barra do futuro, então isso nunca traz dado
    inventado, só evita perder as últimas barras por causa do fuso da
    máquina que roda o botão ser diferente do fuso do corretor."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    chamadas = {}

    def fake_buscar(symbol, desde, ate):
        chamadas["ate"] = ate
        return pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        })

    monkeypatch.setattr(src, "buscar_barras", fake_buscar)
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)
    antes = datetime.now()

    src.sincronizar(con, "WIN$N", price_decimals=0)

    assert chamadas["ate"] >= antes + timedelta(hours=12)


def test_sincronizar_nao_engole_yaml_de_instrumento_ausente(con, tmp_path, monkeypatch):
    """cli.py cmd_ingest deixa FileNotFoundError estourar quando o YAML do
    instrumento não existe — sincronizar não pode seguir em frente sem
    rollover_policy como se estivesse tudo bem. O erro vem embrulhado em
    MT5Error (mesmo caminho da reconstrução que falha, ver o teste
    `test_sincronizar_avisa_quando_ingest_ok_mas_reconstrucao_falha`), com
    a causa original preservada em `__cause__`."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "SEM$YAML", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(
        src, "buscar_barras",
        lambda symbol, desde, ate: pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        }),
    )
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)

    with pytest.raises(src.MT5Error, match="barras novas já foram gravadas") as excinfo:
        src.sincronizar(con, "SEM$YAML", price_decimals=0)
    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


def test_sincronizar_duas_vezes_na_mesma_janela_nao_sobrescreve_o_tsv(con, tmp_path, monkeypatch):
    """O nome do arquivo bruto precisa ter resolução fina o bastante para
    duas sincronizações seguidas (ex: clique duplo) não se sobrescreverem —
    senão a cópia bruta da primeira some sem deixar rastro."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(
        src, "buscar_barras",
        lambda symbol, desde, ate: pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        }),
    )
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)

    src.sincronizar(con, "WIN$N", price_decimals=0)
    src.sincronizar(con, "WIN$N", price_decimals=0)

    arquivos = list((tmp_path / "raw").glob("mt5_sync_*.tsv"))
    assert len(arquivos) == 2


# ---------------------------------------------------- conectar/desconectar

class _FakeMT5Conexao:
    TIMEFRAME_M1 = 1

    def __init__(self, inicializa=True):
        self._inicializa = inicializa
        self.desligado = False

    def initialize(self):
        return self._inicializa

    def last_error(self):
        return (-1, "terminal não encontrado")

    def shutdown(self):
        self.desligado = True


def test_conectar_recusa_com_mensagem_clara_se_terminal_fechado(monkeypatch):
    fake = _FakeMT5Conexao(inicializa=False)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    with pytest.raises(src.MT5Error, match="Abra o MetaTrader 5"):
        src.conectar()


def test_desconectar_chama_shutdown(monkeypatch):
    fake = _FakeMT5Conexao(inicializa=True)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    src.desconectar()

    assert fake.desligado is True


def test_sincronizar_desconecta_mesmo_se_buscar_barras_falhar(con, tmp_path, monkeypatch):
    """conectar()/desconectar() precisam envolver buscar_barras num
    finally — senão um erro no meio (símbolo ruim, sem histórico) deixa a
    conexão presa no terminal."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    chamadas = {"conectou": False, "desconectou": False}

    def fake_conectar():
        chamadas["conectou"] = True

    def fake_desconectar():
        chamadas["desconectou"] = True

    def fake_buscar_que_falha(symbol, desde, ate):
        raise src.MT5Error("falha proposital do teste")

    monkeypatch.setattr(src, "conectar", fake_conectar)
    monkeypatch.setattr(src, "desconectar", fake_desconectar)
    monkeypatch.setattr(src, "buscar_barras", fake_buscar_que_falha)

    with pytest.raises(src.MT5Error, match="falha proposital"):
        src.sincronizar(con, "WIN$N", price_decimals=0)

    assert chamadas["conectou"] is True
    assert chamadas["desconectou"] is True


def test_sincronizar_conecta_e_desconecta_uma_vez_no_caminho_de_sucesso(con, tmp_path, monkeypatch):
    """Sem barras_que_falha no meio, conectar/desconectar continuam
    acontecendo — exatamente uma vez cada, não zero (regressão que
    esconderia a chamada real ao terminal) nem duas (desconectar chamado
    tambem fora do finally, por engano)."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    contagem = {"conectou": 0, "desconectou": 0}

    monkeypatch.setattr(src, "conectar", lambda: contagem.__setitem__("conectou", contagem["conectou"] + 1))
    monkeypatch.setattr(src, "desconectar", lambda: contagem.__setitem__("desconectou", contagem["desconectou"] + 1))
    monkeypatch.setattr(
        src, "buscar_barras",
        lambda symbol, desde, ate: pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        }),
    )

    src.sincronizar(con, "WIN$N", price_decimals=0)

    assert contagem == {"conectou": 1, "desconectou": 1}


def test_sincronizar_avisa_quando_ingest_ok_mas_reconstrucao_falha(con, tmp_path, monkeypatch):
    """rebuild_trading_days/rebuild_rollovers/export_parquet rodam DEPOIS
    do commit do ingest_csv — se um deles falhar, as barras novas já estão
    gravadas. A mensagem de erro precisa dizer isso, em vez de "erro
    inesperado" genérico escondendo que parte do trabalho já aconteceu."""
    seed = tmp_path / "seed.tsv"
    ts0 = datetime(2026, 9, 1, 9, 0)
    from tests.test_ingest import write_export
    write_export(seed, [(ts0, 100000, 100050, 99950, 100010)])
    ing.ingest_csv(con, seed, "WIN$N", price_decimals=0)

    monkeypatch.setattr(db, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(src, "conectar", lambda: None)
    monkeypatch.setattr(src, "desconectar", lambda: None)
    monkeypatch.setattr(
        src, "buscar_barras",
        lambda symbol, desde, ate: pl.DataFrame({
            "ts": [datetime(2026, 9, 2, 9, 0)],
            "open": [100010], "high": [100060], "low": [99960], "close": [100020],
            "tick_volume": [80], "volume": [0], "spread": [5],
        }),
    )

    def rebuild_que_falha(con, symbol):
        raise RuntimeError("falha proposital na reconstrução")

    monkeypatch.setattr(src.cal, "rebuild_trading_days", rebuild_que_falha)

    with pytest.raises(src.MT5Error, match="barras novas já foram gravadas"):
        src.sincronizar(con, "WIN$N", price_decimals=0)
