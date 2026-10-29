import numpy as np
from scripts.foto_win import comparar

def _f(pnl):
    return {"planos": {7: {False: {"n_trades": 1, "trades": {"pnl": np.array(pnl)}}}},
            "estrategias": {"reversao_rsi": {"n_trades": 1, "trades": {"pnl": np.array(pnl)}}}}

def test_identico_nao_tem_diferenca():
    assert comparar(_f([1.0, 2.0]), _f([1.0, 2.0])) == []

def test_diferenca_e_apontada_com_o_caminho():
    difs = comparar(_f([1.0, 2.0]), _f([1.0, 2.5]))
    assert difs and all("pnl" in d for d in difs)
    assert any("planos/7" in d for d in difs) and any("estrategias/reversao_rsi" in d for d in difs)

def test_chave_que_some_e_diferenca():
    a = _f([1.0]); b = _f([1.0]); del b["planos"][7]
    assert any("planos/7" in d for d in comparar(a, b))


def test_gerar_tem_as_cinco_partes(monkeypatch):
    from scripts import foto_win
    for nome in ("_planos", "_estrategias", "_mineracao", "_walkforward", "_candidata"):
        monkeypatch.setattr(foto_win, nome, lambda *a, **k: {})
    assert set(foto_win.gerar()) == {"planos", "estrategias", "mineracao",
                                     "walkforward", "candidata"}


def test_conferir_usa_o_banco_congelado(monkeypatch, tmp_path):
    import pickle
    from scripts import foto_win
    monkeypatch.setattr(foto_win, "PASTA_FOTOS", tmp_path)
    (tmp_path / "x.pkl").write_bytes(pickle.dumps({}))
    (tmp_path / "x.duckdb").write_bytes(b"")
    vistos = []
    monkeypatch.setattr(foto_win, "gerar", lambda banco=None: vistos.append(banco) or {})
    assert foto_win.main(["conferir", "x"]) == 0
    assert vistos == [tmp_path / "x.duckdb"]
    (tmp_path / "x.duckdb").unlink()
    assert foto_win.main(["conferir", "x"]) == 0
    assert vistos[-1] is None
