"""Acesso a dados para a interface.

Duas regras aqui:

1. Nunca mandar 688 mil candles para o navegador. A janela visivel e
   agregada no DuckDB para o timeframe adequado e limitada a MAX_CANDLES.

2. As barras completas ficam em cache no processo. Um backtest custa ~50 ms,
   mas carregar 688 mil barras do banco custa ~90 ms - recarregar a cada
   clique seria o gargalo da interface, nao o motor.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import numpy as np

from core import captura as CAP
from core import db_manager as db
from core.engine.execution import prepare_bars

MAX_CANDLES = 4000

TIMEFRAMES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": None,
}

_bars_cache: dict[str, dict] = {}
_meta_cache: dict[str, dict] = {}


def bars(symbol: str) -> dict:
    # O Flask atende em várias threads e `estado_captura` pode limpar o cache
    # entre guardar e devolver: devolve o que carregou, não o que está lá.
    b = _bars_cache.get(symbol)
    if b is None:
        with db.connect(read_only=True) as con:
            b = prepare_bars(con, symbol)
        _bars_cache[symbol] = b
    return b


ESTADO_CAPTURA = db.DATA / "ao_vivo" / "estado.json"
_estado_ultimo: dict | None = None
_conferencia_vista: str | None = None


def estado_captura() -> dict | None:
    """O `estado.json` do serviço de captura, ou None se ele nunca rodou.

    Arquivo ilegível (pego no meio de uma troca no Windows) devolve a última
    leitura boa: piscar "captura nunca rodou" por um instante assustaria.
    """
    global _estado_ultimo, _conferencia_vista
    if not ESTADO_CAPTURA.exists():
        _estado_ultimo = None
        return None
    e = CAP.ler_estado(ESTADO_CAPTURA)
    if not isinstance(e, dict):
        return _estado_ultimo
    _estado_ultimo = e
    # A reconferência da manhã e a conferência de um dia recuperado também
    # reescrevem barras com a conferência de hoje ainda pendente: a captura
    # publica isso em `base_alterada_em`. Vale a mais recente das marcas:
    # ISO 8601 ordena como texto.
    marcas = [m for m in ((e.get("conferencia") or {}).get("em"),
                          (e.get("reconferencia") or {}).get("em"),
                          e.get("base_alterada_em"))
              if isinstance(m, str)]
    em = max(marcas) if marcas else None
    # sem "em" (serviço reaberto, conferência pendente) não esquece a última
    # vista: senão a conferência seguinte pareceria a primeira e não limparia
    if em is not None and em != _conferencia_vista:
        # a conferência do dia reescreveu candles no banco: sem limpar, o
        # backtest e a mineração seguiriam com as barras de antes dela
        if _conferencia_vista is not None:
            _bars_cache.clear()
        _conferencia_vista = em
    return e


# Selo das ordens no topo (spec ordens §8). O texto é o que o usuário lê de
# relance em qualquer aba; a dica (title) leva o resto.
_SELO_TEXTO = {
    "enviando": "Demo · enviando ordens",
    "desligado": "Demo · envio desligado",
    "travada": "Demo · conta travada até amanhã",
    "sem_captura": "Ordens paradas · sem captura",
    "sem_demo": "Sem demo",
}


def _posicoes_da_automacao(o: dict) -> int:
    return sum(len((l or {}).get("posicoes") or [])
               for l in (o.get("ligacoes") or {}).values())


def _tem_demo(o: dict) -> bool:
    """Alguma ligação desta conta está na fase demo? O estado não traz a
    fase; o passo marca as que estão no papel com o motivo "fase papel" (e
    as de outra conta com "conta de outro portfólio"), e só a zera geral
    (zerar tudo, trava) apaga esse motivo — e aí o selo já é outro."""
    fora = ("fase papel", "conta de outro portfólio")
    return any((l or {}).get("motivo") not in fora
               for l in (o.get("ligacoes") or {}).values())


def ordens_do_estado(e: dict | None, agora: datetime | None = None) -> dict:
    """O selo das ordens e o alarme, só a partir do `estado.json`.

    `selo`: enviando | desligado | travada | sem_captura | sem_demo.
    `alarme`: chamado aberto, conta travada ou o caminho das ordens com erro
    — o som e o título piscando (`assets/alarme.js`). `chaves` identifica
    cada motivo de alarme pela hora em que abriu: o bipe toca uma vez por
    chamado novo, e um chamado que fecha e reabre é novo.
    `posicoes`: posições da automação na corretora (None = não se sabe)."""
    # import aqui: o pregao_panel importa este módulo (to_epoch)
    from .components.pregao_panel import captura_ativa

    agora = agora or datetime.now()

    def r(selo, texto=None, chamados=(), alarme=False, chaves=(), posicoes=None):
        return {"selo": selo, "texto": texto or _SELO_TEXTO[selo],
                "chamados": list(chamados), "alarme": bool(alarme),
                "chaves": "|".join(chaves), "posicoes": posicoes}

    # Mesma régua do selo da captura: estado velho não prova nada — nem o
    # Envio, nem os chamados (já podem ter fechado). O selo da captura, ao
    # lado, já está vermelho; tocar alarme aqui seria o mesmo aviso duas vezes.
    if not captura_ativa(e, agora):
        return r("sem_captura")
    o = e.get("ordens")
    if not isinstance(o, dict) or not o:
        # captura sem o caminho das ordens (sem o YAML do ativo, ou ainda
        # não deu a primeira volta)
        return r("sem_demo")

    chamados = [c for c in (o.get("chamados") or []) if isinstance(c, dict)]
    chaves = [f"{c.get('chave')}@{c.get('desde')}" for c in chamados]
    posicoes = _posicoes_da_automacao(o) if "ligacoes" in o else None

    def com_alarme(selo, texto=None, extra=False, chave_extra=None):
        ks = chaves + ([chave_extra] if chave_extra else [])
        return r(selo, texto, chamados, bool(chamados) or extra, ks, posicoes)

    if o.get("erro"):
        # o captura.py abre o chamado `ordens_falhou`, mas este bloco curto
        # não traz a lista: o alarme vem do próprio erro
        return com_alarme("desligado", "Demo · ordens com erro (veja a janela "
                          "da captura)", extra=True,
                          chave_extra=f"erro@{o.get('vivo_em')}")
    trava = o.get("travada")
    if trava:
        return com_alarme("travada", extra=True,
                          chave_extra=f"travada@{(trava or {}).get('desde')}")
    if o.get("parado"):
        # fora do pregão, MT5 fora do ar: nada sai agora, ligado ou não
        return com_alarme("desligado", f"Demo · parado ({o['parado']})")
    if o.get("foto") == "falhou":
        return com_alarme("desligado", "Demo · sem leitura da corretora agora")
    conta = o.get("conta") or {}
    if conta.get("conta_id") is None:
        # MT5 logado numa conta que não está cadastrada (ou nenhuma conta
        # cadastrada): a automação não manda nada nela
        login = conta.get("login")
        texto = (f"Sem demo · MT5 na conta {login}, não cadastrada"
                 if login else None)
        return com_alarme("sem_demo", texto)
    if o.get("zerar"):
        return com_alarme("desligado", "Demo · zerando tudo")
    if not _tem_demo(o):
        return com_alarme("sem_demo", "Sem demo · nenhuma variante na fase demo")
    if o.get("envio"):
        return com_alarme("enviando")
    return com_alarme("desligado")


def instrumentos() -> list[dict]:
    """Os instrumentos que TÊM barras, do mais populoso para o menos.

    A plataforma nasceu no mini índice, mas nunca foi só dele: o símbolo
    saiu do código e passou a vir daqui, para que acrescentar um ativo seja
    ingerir um CSV e não editar Python.
    """
    with db.connect(read_only=True) as con:
        linhas = con.execute("""
            SELECT i.symbol, i.description, count(b.ts) AS n
            FROM instruments i JOIN bars_m1 b USING (symbol)
            GROUP BY i.symbol, i.description
            ORDER BY n DESC
        """).fetchall()
    return [{"symbol": s, "descricao": d, "barras": int(n)} for s, d, n in linhas]


def instrument(symbol: str) -> dict:
    if symbol not in _meta_cache:
        _meta_cache[symbol] = db.load_instrument_yaml(symbol)
    return _meta_cache[symbol]


def span(symbol: str) -> tuple[datetime, datetime]:
    ts = bars(symbol)["ts"]
    return ts[0].astype("datetime64[s]").item(), ts[-1].astype("datetime64[s]").item()


def to_epoch(ts) -> int:
    """Timestamps sao horario de Brasilia sem fuso. A biblioteca de grafico
    interpreta o numero como UTC, entao mandamos o horario de parede como se
    fosse UTC - assim o eixo mostra 09:00 quando o pregao abriu 09:00."""
    return int(np.datetime64(ts, "s").astype("int64"))


def auto_timeframe(inicio: datetime, fim: datetime) -> str:
    """Maior resolucao que cabe em MAX_CANDLES para a janela pedida."""
    minutos = max(1, int((fim - inicio).total_seconds() // 60))
    for nome, passo in TIMEFRAMES.items():
        if passo is None:
            return nome
        if minutos / passo <= MAX_CANDLES:
            return nome
    return "D1"


def candles(symbol: str, inicio: datetime, fim: datetime, tf: str = "auto") -> dict:
    """Candles agregados para a janela visivel."""
    if tf == "auto":
        tf = auto_timeframe(inicio, fim)
    passo = TIMEFRAMES[tf]

    if passo is None:
        bucket = "CAST(ts AS DATE)"
    else:
        bucket = f"time_bucket(INTERVAL '{passo} minutes', ts)"

    with db.connect(read_only=True) as con:
        rows = con.execute(
            f"""
            SELECT {bucket} AS t,
                   first(open  ORDER BY ts) AS o,
                   max(high)                AS h,
                   min(low)                 AS l,
                   last(close ORDER BY ts)  AS c,
                   sum(tick_volume)         AS v
            FROM bars_m1
            WHERE symbol = ? AND ts >= ? AND ts <= ?
            GROUP BY 1 ORDER BY 1
            LIMIT {MAX_CANDLES}
            """,
            [symbol, inicio, fim],
        ).fetchall()

    return {
        "timeframe": tf,
        "candles": [
            {"time": to_epoch(r[0]), "open": r[1], "high": r[2],
             "low": r[3], "close": r[4]}
            for r in rows
        ],
        "volume": [
            {"time": to_epoch(r[0]), "value": int(r[5]),
             "color": "rgba(72,190,146,.35)" if r[4] >= r[1] else "rgba(229,128,110,.35)"}
            for r in rows
        ],
    }


def default_window(symbol: str, dias: int = 5) -> tuple[datetime, datetime]:
    _, fim = span(symbol)
    return fim - timedelta(days=dias), fim


def dia_do_pregao(estado: dict | None) -> date:
    """O dia que a sub-tela Pregão desenha: o do último candle gravado.

    Vale o mais novo entre o `ultimo_salvo` da captura e o banco: com a
    captura parada há dias, o "Sincronizar com MT5" pode ter trazido
    pregões depois do que o estado.json lembra."""
    dias = []
    salvo = (estado or {}).get("ultimo_salvo")
    if salvo:
        try:
            dias.append(datetime.fromisoformat(str(salvo)).date())
        except ValueError:
            pass
    try:
        with db.connect(read_only=True, tentativas=4) as con:
            ultimo = con.execute("SELECT max(ts) FROM bars_m1 WHERE symbol = ?",
                                 [(estado or {}).get("simbolo") or "WIN$N"]
                                 ).fetchone()[0]
    except (duckdb.Error, RuntimeError):
        # banco sem a tabela ainda, ou ocupado: o estado basta
        ultimo = None
    if ultimo is not None:
        dias.append(ultimo.date())
    return max(dias) if dias else date.today()


def m1_fechados(symbol: str, inicio: datetime, fim: datetime) -> list[dict]:
    """Os candles M1 já gravados em [inicio, fim) — o que já fechou do balde
    de 5 ou 15 min que está em formação.

    Espera pouco pelo banco: isto roda no pulso de 2 s da tela; travar 15 s
    esperando uma mineração terminar de gravar empilharia pulsos. Ocupado,
    levanta RuntimeError e o pulso pula a vez."""
    with db.connect(read_only=True, tentativas=4) as con:
        linhas = con.execute(
            "SELECT ts, open, high, low, close FROM bars_m1 "
            "WHERE symbol = ? AND ts >= ? AND ts < ? ORDER BY ts",
            [symbol, inicio, fim]).fetchall()
    return [{"ts": ts, "open": o, "high": h, "low": l, "close": c}
            for ts, o, h, l, c in linhas]
