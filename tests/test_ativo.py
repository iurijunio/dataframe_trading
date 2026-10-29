from datetime import datetime
import polars as pl
from core import ativo
from core import db_manager as db

WIN = ativo.ficha_de({"symbol": "WIN$N", "currency": "BRL", "timezone": "America/Sao_Paulo",
                      "price_decimals": 0, "tick_size": 5, "point_value": 0.20, "tick_value": 1.0})
MES = ativo.ficha_de({"symbol": "MES", "currency": "USD", "timezone": "America/New_York",
                      "price_decimals": 2, "tick_size": 0.25, "point_value": 5.0, "tick_value": 1.25,
                      "sessao_abertura": "18:00", "abertura_referencia": "09:30"})

def _pregao(utc):
    df = pl.DataFrame({"t": [utc]}).with_columns(pl.col("t").dt.replace_time_zone("UTC"))
    return df.select(ativo.utc_para_pregao(pl.col("t"), MES)).item()

def test_derivados_mes():
    assert (MES.escala, MES.tick_unid, MES.deslocamento_min, MES.abertura_min) == (100, 25, 360, 930)
    assert MES.valor_por_unid == 0.05

def test_win_e_identidade():
    assert (WIN.escala, WIN.tick_unid, WIN.deslocamento_min, WIN.abertura_min) == (1, 5, 0, None)
    t = datetime(2026, 10, 28, 9, 0)
    assert ativo.hora_para_exibir(t, WIN) == t
    assert ativo.hora_para_motor("09:00", WIN) == "09:00"
    assert ativo.preco_para_exibir(197760, WIN) == 197760 and isinstance(ativo.preco_para_exibir(197760, WIN), int)

def test_domingo_18h_ny_cai_na_segunda_no_verao():          # UTC-4
    assert _pregao(datetime(2024, 6, 16, 22, 0)) == datetime(2024, 6, 17, 0, 0)

def test_domingo_18h_ny_cai_na_segunda_no_inverno():        # UTC-5
    assert _pregao(datetime(2024, 1, 7, 23, 0)) == datetime(2024, 1, 8, 0, 0)

def test_ultima_barra_16h59_ny_e_23h59_do_pregao():
    assert _pregao(datetime(2024, 6, 17, 20, 59)) == datetime(2024, 6, 17, 22, 59)

def test_virada_do_horario_de_verao_marco_2024():
    # domingo 10/03/2024: NY passa a UTC-4; o pregão de segunda abre 22:00 UTC
    assert _pregao(datetime(2024, 3, 10, 22, 0)) == datetime(2024, 3, 11, 0, 0)
    # sexta anterior (UTC-5): 16:59 NY = 21:59 UTC
    assert _pregao(datetime(2024, 3, 8, 21, 59)) == datetime(2024, 3, 8, 22, 59)

def test_ida_e_volta_de_hora():
    assert ativo.hora_para_motor("09:30", MES) == "15:30"
    assert ativo.hora_para_motor("18:00", MES) == "00:00"
    assert ativo.hora_para_exibir(datetime(2024, 6, 17, 15, 30), MES) == datetime(2024, 6, 17, 9, 30)
    assert ativo.hora_para_exibir(datetime(2024, 6, 17, 1, 0), MES) == datetime(2024, 6, 16, 19, 0)

def test_preco_mes():
    assert ativo.preco_para_exibir(543225, MES) == 5432.25
def test_fichas_dos_micros():
    mes, mnq = ativo.ficha("MES"), ativo.ficha("MNQ")
    assert (mes.point_value, mes.tick_value, mes.tick_unid, mes.currency) == (5.0, 1.25, 25, "USD")
    assert (mnq.point_value, mnq.tick_value, mnq.tick_unid) == (2.0, 0.50, 25)
    assert mes.deslocamento_min == mnq.deslocamento_min == 360
    assert set(mes.pregoes_descartados) == {"2020-03-02", "2020-03-03", "2022-06-21", "2026-10-12"}

def test_banco_guarda_tick_em_unidades_guardadas():
    with db.connect() as con:
        db.init_schema(con); db.sync_instruments(con)
        lin = dict(con.execute("SELECT symbol, tick_size FROM instruments").fetchall())
    assert lin["MES"] == 25 and lin["WIN$N"] == 5
