"""O formato do preco no grafico segue o ativo: MES tem centavos, WIN nao."""
from ui import theme as T
from ui.components import charts


def _dados():
    return {"candles": [], "volume": []}


def _fmt(simbolo):
    s = charts.price_series(_dados(), simbolo=simbolo) if simbolo else charts.price_series(_dados())
    return s[0]["options"]["priceFormat"]


def test_mes_tem_duas_casas_e_passo_de_um_quarto():
    f = _fmt("MES")
    assert f["precision"] == 2 and f["minMove"] == 0.25 and f["type"] == "price"


def test_win_continua_exatamente_como_antes():
    esperado = {"type": "price", "precision": 0, "minMove": 5}
    for simbolo in ("WIN$N", None):
        f = _fmt(simbolo)
        assert f == esperado
        assert type(f["precision"]) is int and type(f["minMove"]) is int
    assert charts.price_series(_dados(), simbolo="WIN$N")[0]["options"] == T.CANDLE_OPTIONS


def test_nao_muta_o_tema_compartilhado():
    charts.price_series(_dados(), simbolo="MES")
    assert T.CANDLE_OPTIONS["priceFormat"] == {"type": "price", "precision": 0, "minMove": 5}


def _desenhar(monkeypatch, simbolo):
    from datetime import datetime
    from ui import callbacks, data as D
    from dash import Dash
    capturado = {}

    class _App(Dash):
        def callback(self, *a, **k):
            def deco(fn):
                capturado.setdefault(fn.__name__, []).append(fn)
                return fn
            return deco

    monkeypatch.setattr(D, "candles", lambda s, de, ate, tf="auto": {
        "candles": [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}],
        "volume": [], "timeframe": "M1"})
    app = _App(__name__)
    try:
        callbacks.register(app)
    except Exception:
        pass
    janela = {"de": "2026-01-05T09:00:00", "ate": "2026-01-05T17:00:00"}
    fn = next(f for f in capturado["desenhar"]
              if f.__code__.co_varnames[:4] == ("janela", "tf", "run", "ativo"))
    return fn(janela, "M1", None, simbolo)


def test_info_da_janela_vai_para_hora_de_ny_no_mes(monkeypatch):
    series, _, info, _ = _desenhar(monkeypatch, "MES")
    assert "03:00" in info and "11:00" in info          # 09:00/17:00 menos 360 min
    assert series[0]["options"]["priceFormat"]["precision"] == 2


def test_info_da_janela_do_win_nao_muda(monkeypatch):
    series, _, info, _ = _desenhar(monkeypatch, "WIN$N")
    assert "09:00" in info and "17:00" in info
    assert series[0]["options"]["priceFormat"] == {"type": "price", "precision": 0, "minMove": 5}
