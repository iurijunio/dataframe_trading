"""O papel: o que cada variante teria feito no pregão de hoje, ao vivo.

Spec: docs/superpowers/specs/2026-10-02-ao-vivo-papel-design.md §4.

A regra que manda em tudo aqui é a decisão 1 do usuário: o papel é **igual
ao backtest**. Não "parecido": mesmo `run_strategy`, mesmos candles, mesma
montagem de perfil que o walk-forward usou para gerar o plano
(`wfa_runner.trades_oos_detalhados`). Por isso não existe um motor de papel
— existe o motor de sempre, rodado sobre o dia.

E é rodado sobre o dia INTEIRO, a cada candle novo (decisão 3). Guardar a
posição em memória e ir atualizando seria um segundo motor, com as suas
próprias regras de stop, breakeven e fechamento — e o dia em que os dois
discordassem ninguém saberia qual estava certo. Recalculando tudo, a
operação de papel é por construção a mesma do backtest; o preço é rodar o
motor uma vez por minuto sobre alguns milhares de barras, o que custa
milissegundos. De bônus, queda e reinício da captura não perdem nada: a
volta seguinte recalcula o dia do zero.

O que o recálculo inteiro exige em troca:
  - **aquecimento**: os indicadores precisam do mesmo passado que tinham no
    histórico inteiro, senão o sinal de hoje sai diferente
    (`pregoes_de_aquecimento`);
  - **identidade da operação**: a mesma operação recalculada vira a mesma
    linha, com o mesmo `op_id` — a parte 4 liga a ordem real a ele
    (`gravar`, upsert pela entrada);
  - **posição aberta**: o motor trata o dia incompleto como pregão que
    fechou cedo e encerra na última barra. Isso é a marcação a mercado
    pronta — só falta reconhecer que ela é provisória (`calcular`).

Nada aqui importa Dash: o serviço de captura chama `rodar_dia` fora da
conexão de escrita e `gravar` dentro dela (spec §4.4.6).
"""
from __future__ import annotations

import importlib
import logging
import math
import sys
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import numpy as np

from . import codigo
from . import db_manager as db
from . import engine
from . import metrics
from . import plano as _plano
from . import variantes as V
from .engine import kernel as K
from .engine.execution import (TIMEFRAMES, ExecutionProfile, _minutes,
                               prepare_bars, run_strategy)
from .wfa_runner import CAMPOS_EXECUCAO_NOMES

log = logging.getLogger(__name__)

SIMBOLO = "WIN$N"

# 09:00 a 18:24. É o pregão cheio do WIN: dia mais curto só faz o
# aquecimento sobrar, nunca faltar.
MINUTOS_PREGAO = 565

# Nomes que denunciam "quantas barras para trás este parâmetro olha". A
# regra é por nome porque a estratégia só declara default/min/max — não diz
# qual parâmetro é janela. Errar para mais (um parâmetro que não é janela
# mas tem o nome) só custa barras; errar para menos muda o sinal.
_PALAVRAS_PERIODO = ("periodo", "media", "canal", "janela", "tendencia",
                     "lenta", "rapida")

# Pregão que não se recalcula mais: conferido (o dia acabou e os candles
# foram conferidos) e interrompido (o código mudou no meio — decisão 5).
CONGELADOS = ("conferido", "interrompido")

# A saída que o motor dá a uma posição que ainda está viva: o dia
# incompleto parece um pregão que fechou cedo (motivo 3) ou o fim dos dados
# (motivo 5). Stop, alvo, sinal ou tempo na última barra aconteceram de fato.
_SAIDAS_DE_CORTE = (K.EXIT_CLOSE_TIME, K.EXIT_DATA_END)

# "nada está aberto": passado como horário de fechamento na conferência, o
# dia acabou e a última barra é o fechamento real, mesmo num pregão curto
FECHAMENTO_DIA_ENCERRADO = "00:00"


# --------------------------------------------------------------- montagem
def perfil_do_plano(plano: dict) -> tuple[dict, ExecutionProfile]:
    """`(parâmetros da estratégia, perfil)` exatamente como o walk-forward
    montou para gerar os números do plano (`wfa_runner.py:359-362`).

    O plano grava em `params` os campos de execução que a mineração varreu
    (stop, alvo, breakeven...) junto com os da estratégia: eles valem POR
    CIMA do perfil base. Nunca `ExecutionProfile.from_config` — ele lê o
    formato de blocos da tela e, com o retrato plano gravado aqui,
    devolveria o perfil padrão sem avisar.
    """
    params = plano.get("params") or {}
    exec_ = {k: v for k, v in params.items() if k in CAMPOS_EXECUCAO_NOMES}
    estrat = {k: v for k, v in params.items() if k not in CAMPOS_EXECUCAO_NOMES}
    # o papel opera os contratos do PLANO (decisão 8), não o modo de
    # dimensionamento do perfil — risco por operação dependeria da curva
    perfil = replace(ExecutionProfile(**(plano.get("profile") or {})), **exec_,
                     modo_posicao="contratos_fixos",
                     contratos=int(plano["contratos"]))
    return estrat, perfil


def pregoes_de_aquecimento(estrategia_mod, params: dict,
                           perfil: ExecutionProfile) -> int:
    """Quantos pregões ANTES do dia o motor precisa ver para o sinal de hoje
    sair igual ao do histórico inteiro (spec §4.3).

    Medido no banco real: 10 pregões não bastam (`reversao_rsi` com
    tendência 600 em M15 divergiu em 32 de 59 pregões). A conta é a janela
    mais longa em minutos — maior período da estratégia mais o ATR do stop
    ou alvo — dividida pelo pregão, com 2 de folga para o pregão curto e
    para a barra a mais que todo "primeiro rompimento" olha.

    Estratégia com indicador recursivo (média exponencial) nunca esquece o
    passado: ela declara `aquecimento_barras(params)`, que tem prioridade.
    """
    min_tf = TIMEFRAMES.get(perfil.timeframe, 1)
    declarado = getattr(estrategia_mod, "aquecimento_barras", None)
    if callable(declarado):
        maior = int(declarado(params))
    else:
        valores = [int(v) for k, v in (params or {}).items()
                   if any(p in k for p in _PALAVRAS_PERIODO)
                   and isinstance(v, (int, float)) and not isinstance(v, bool)
                   and float(v).is_integer()]
        maior = max(valores, default=0)
    atr = max(perfil.stop_atr_periodo if perfil.stop_tipo == "atr" else 0,
              perfil.alvo_atr_periodo if perfil.alvo_tipo == "atr" else 0)
    return math.ceil((maior * min_tf + atr * min_tf) / MINUTOS_PREGAO) + 2


# ------------------------------------------------------------------ barras
def _limites(dia: date) -> tuple[datetime, datetime]:
    ini = datetime.combine(dia, time())
    return ini, ini + timedelta(days=1)


def _tem_candle(con, symbol: str, dia: date) -> bool:
    ini, fim = _limites(dia)
    return con.execute("SELECT 1 FROM bars_m1 WHERE symbol = ? AND ts >= ? "
                       "AND ts < ? LIMIT 1", [symbol, ini, fim]).fetchone() \
        is not None


def barras_do_dia(con, symbol: str, dia: date, pregoes: int) -> dict | None:
    """O dia (até o último candle gravado) e os `pregoes` anteriores a ele.

    Do BANCO, não do Parquet: as barras de hoje só chegam ao espelho na
    conferência. Os pregões anteriores contam pelas datas que existem em
    `bars_m1` — o `trading_days` só ganha o dia depois da conferência, e um
    calendário de feriados não saberia do pregão que faltou no histórico.
    `None` sem candle no dia: fim de semana, feriado, antes da abertura.
    """
    if not _tem_candle(con, symbol, dia):
        return None
    ini, fim = _limites(dia)
    datas = con.execute(
        "SELECT DISTINCT CAST(ts AS DATE) AS d FROM bars_m1 "
        "WHERE symbol = ? AND ts < ? ORDER BY d DESC LIMIT ?",
        [symbol, ini, max(int(pregoes), 0)]).fetchall()
    inicio = min(r[0] for r in datas) if datas else dia
    return prepare_bars(con, symbol, start=datetime.combine(inicio, time()),
                        end=fim - timedelta(microseconds=1))


def checksum(con, symbol: str, dia: date) -> str:
    """Impressão dos candles do dia: quantidade e soma de cada preço. Basta
    para acusar reimportação, Sincronizar ou reparo que mexeu no dia depois
    da conferência (decisão 6) — não é segurança, é conferência."""
    ini, fim = _limites(dia)
    r = con.execute("SELECT count(*), sum(open), sum(high), sum(low), "
                    "sum(close) FROM bars_m1 WHERE symbol = ? AND ts >= ? "
                    "AND ts < ?", [symbol, ini, fim]).fetchone()
    return ":".join(str(int(x or 0)) for x in r)


# ------------------------------------------------------------------ cálculo
def _dt(x) -> datetime:
    return np.datetime64(x, "us").item()


def calcular(barras: dict, dia: date, plano: dict, mod, inst: dict,
             fechamento_hhmm: str | None = None) -> list[dict]:
    """As operações com entrada no `dia`, pelo motor de sempre. Puro.

    `fechamento_hhmm`: o horário abaixo do qual uma saída forçada na última
    barra é corte do dado, não fechamento — `None` usa o do perfil;
    `FECHAMENTO_DIA_ENCERRADO` diz que o dia acabou e nada está aberto.

    Aberta ⇔ saiu na última barra, por fechamento ou fim dos dados, antes
    do horário de fechamento: o motor encerrou só porque o dado acabou. O
    resultado dela é a marcação a mercado que ele já fez (fechamento da
    última barra com a derrapagem do perfil) — provisório, mas o mesmo
    número que a operação teria se o pregão acabasse agora.
    """
    estrat, perfil = perfil_do_plano(plano)
    n = len(barras["ts"])
    if n == 0:
        return []
    ultimo = int(barras["ts"][n - 1].astype("datetime64[m]").astype(np.int64)
                 % 1440)
    encerrado = fechamento_hhmm == FECHAMENTO_DIA_ENCERRADO
    corte = ultimo < _minutes(fechamento_hhmm or perfil.fechamento)
    # a vela do timeframe da última barra ainda não fechou pelo relógio:
    # para o stop/alvo, só vale a vela anterior (ver `run_strategy`). Dia
    # encerrado não tem vela aberta: a última vela do pregão termina na
    # última barra dele, no histórico inteiro também.
    passo = TIMEFRAMES.get(perfil.timeframe, 1)
    vela_aberta = (passo > 1 and not encerrado
                   and (ultimo // passo) * passo + passo - 1 > ultimo)
    res = run_strategy(barras, mod, estrat, perfil, inst,
                       vela_aberta=vela_aberta)
    if res.n_trades == 0:
        return []
    din = metrics.monetize(res)
    t = res.trades
    no_dia = np.flatnonzero(t["entry_ts"].astype("datetime64[D]")
                            == np.datetime64(dia, "D"))
    out = []
    for i in no_dia:
        aberta = bool(corte and int(t["exit_i"][i]) == n - 1
                      and int(t["reason"][i]) in _SAIDAS_DE_CORTE)
        stop, alvo = int(t["stop_fim"][i]), int(t["alvo_fim"][i])
        out.append({
            "entry_ts": _dt(t["entry_ts"][i]),
            "exit_ts": None if aberta else _dt(t["exit_ts"][i]),
            "side": int(t["side"][i]),
            "contratos": int(din["contratos"][i]) if np.ndim(din["contratos"])
            else int(din["contratos"]),
            "entry_px": int(t["entry_px"][i]),
            "exit_px": None if aberta else int(t["exit_px"][i]),
            "points": int(t["points"][i]),
            "bruto": float(din["bruto"][i]),
            "custo": float(np.broadcast_to(din["custo"], din["bruto"].shape)[i]),
            "liquido": float(din["liquido"][i]),
            "reason": None if aberta else int(t["reason"][i]),
            "mae": int(t["mae"][i]), "mfe": int(t["mfe"][i]),
            "stop_px": stop or None, "alvo_px": alvo or None,
            "aberta": aberta,
        })
    return out


# --------------------------------------------------------------- ligações
def ligacoes_do_papel(con, symbol: str, dia: date) -> list[dict]:
    """Quem entra no papel do dia (spec §3): toda ligação não removida, já
    adicionada até o fim do dia, ligada ou não (decisão 4: o interruptor só
    marca o que conta).

    O plano é o do dia: o gravado no pregão, se já houver (reinício da
    captura não troca o plano no meio), senão o em vigor. Entra quem tem
    plano do `symbol` — e quem não tem plano nenhum, para o pregão ficar
    registrado como pulado em vez de sumir.
    """
    _ini, fim = _limites(dia)
    linhas = con.execute(
        "SELECT pm.ligacao_id, pm.portfolio_id, pm.variante_id, ev.estrategia, "
        "pp.plano_id FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "LEFT JOIN papel_pregoes pp ON pp.ligacao_id = pm.ligacao_id "
        "     AND pp.dia = ? "
        "WHERE pm.removido_em IS NULL AND pm.adicionado_em < ? "
        "ORDER BY pm.ligacao_id", [dia, fim]).fetchall()
    out = []
    for lig, pf, vid, estrategia, gravado in linhas:
        pid = gravado
        if pid is None:
            vigor = V.plano_em_vigor(vid, dia, con=con)
            pid = vigor["plano_id"] if vigor else None
        if pid is not None:
            r = con.execute("SELECT symbol FROM planos_operacao "
                            "WHERE plano_id = ?", [pid]).fetchone()
            if r is None or r[0] != symbol:
                continue
        out.append({"ligacao_id": int(lig), "portfolio_id": int(pf),
                    "variante_id": int(vid), "estrategia": estrategia,
                    "plano_id": None if pid is None else int(pid)})
    return out


def _linha_do_tempo(con, coluna: str, chave: int, liga: str,
                    desliga: tuple[str, ...], atual: bool):
    """(estado antes do primeiro evento, [(quando, estado)]) pelo diário.

    O diário só guarda as mudanças; o estado antes da primeira é o oposto
    dela. Sem evento nenhum, vale o estado atual da tabela — é o caso da
    ligação migrada de `portfolio_variantes`, que nasceu ligada sem evento.
    """
    tipos = (liga, *desliga)
    eventos = con.execute(
        f"SELECT quando, tipo FROM ao_vivo_eventos WHERE {coluna} = ? "
        f"AND tipo IN ({', '.join('?' * len(tipos))}) "
        "ORDER BY quando, evento_id", [chave, *tipos]).fetchall()
    trocas = [(q, t == liga) for q, t in eventos]
    inicial = (not trocas[0][1]) if trocas else bool(atual)
    return inicial, trocas


def _estado_em(inicial: bool, trocas, instante: datetime) -> bool:
    estado = inicial
    for q, novo in trocas:
        if q > instante:
            break
        estado = novo
    return estado


def periodos_ligados(con, ligacao_id: int, portfolio_id: int,
                     dia: date) -> list[tuple[datetime, datetime]]:
    """Os trechos do dia em que a ligação E o portfólio estavam ligados,
    `[(início, fim))`. Operação com entrada dentro deles conta (decisão 4).

    Não há coluna de horário em `portfolio_membros`: os horários vêm do
    diário. A ligação só existe a partir de `adicionado_em` — adicionada
    hoje, o que entrou antes não conta.
    """
    return periodos_ligados_dias(con, ligacao_id, portfolio_id,
                                 [dia]).get(dia, [])


def periodos_ligados_dias(con, ligacao_id: int, portfolio_id: int,
                          dias) -> dict[date, list[tuple[datetime, datetime]]]:
    """`periodos_ligados` de vários dias lendo o diário uma vez só — a régua
    da expectativa (tela Operação) pergunta isso para cada pregão do plano,
    e tem de ser a MESMA resposta que marcou o `conta` de cada operação."""
    r = con.execute("SELECT pm.adicionado_em, pm.ligada, "
                    "coalesce(pf.ligado, false) FROM portfolio_membros pm "
                    "JOIN portfolios pf ON pf.portfolio_id = pm.portfolio_id "
                    "WHERE pm.ligacao_id = ?", [ligacao_id]).fetchone()
    if r is None:
        return {d: [] for d in dias}
    adicionado, ligada, pf_ligado = r
    lig = _linha_do_tempo(con, "ligacao_id", ligacao_id, "membro_ligado",
                          ("membro_desligado", "membro_removido"), ligada)
    pf = _linha_do_tempo(con, "portfolio_id", portfolio_id, "portfolio_ligado",
                         ("portfolio_desligado",), pf_ligado)
    return {d: _periodos(d, adicionado, lig, pf) for d in dias}


def _periodos(dia, adicionado, lig, pf) -> list[tuple[datetime, datetime]]:
    ini, fim = _limites(dia)
    marcos = {ini, fim}
    for q in [adicionado, *(q for q, _ in lig[1]), *(q for q, _ in pf[1])]:
        if ini < q < fim:
            marcos.add(q)
    marcos = sorted(marcos)
    out: list[tuple[datetime, datetime]] = []
    for a, b in zip(marcos, marcos[1:]):
        if (a >= adicionado and _estado_em(*lig, a) and _estado_em(*pf, a)):
            if out and out[-1][1] == a:
                out[-1] = (out[-1][0], b)
            else:
                out.append((a, b))
    return out


def _conta(entry_ts: datetime, periodos) -> bool:
    return any(a <= entry_ts < b for a, b in periodos)


# --------------------------------------------------------------- código
def _modulo(estrategia: str, hash_disco: str, cache: dict):
    """O módulo da estratégia com o código que está no disco AGORA.

    A captura fica aberta o dia todo e o `strategies.registry` importa uma
    vez só: sem isto, o arquivo editado ao meio-dia seguiria rodando a
    versão da manhã — e a impressão digital diria o contrário. Recarrega
    `strategies.base` junto porque ela entra no hash (`codigo.py`).
    """
    item = cache.get(estrategia)
    if item is not None and item[0] == hash_disco:
        if len(item) > 2:
            # este mesmo arquivo já falhou ao carregar: tentar de novo a
            # cada minuto só repetiria o erro (e o log). Só um arquivo
            # diferente — hash novo — merece outra tentativa.
            raise ImportError(item[2])
        return item[1]
    nome = f"strategies.{estrategia}"
    try:
        if nome in sys.modules:
            importlib.reload(importlib.import_module("strategies.base"))
            mod = importlib.reload(sys.modules[nome])
        else:
            mod = importlib.import_module(nome)
    except Exception as erro:
        # o módulo antigo fica no cache, intacto, junto com o erro: não é
        # usado para este hash, mas também não é jogado fora
        texto = f"código da estratégia não carrega ({type(erro).__name__}: {erro})"
        cache[estrategia] = (hash_disco, item[1] if item else None, texto)
        raise ImportError(texto) from erro
    cache[estrategia] = (hash_disco, mod)
    return mod


# ---------------------------------------------------------------- o dia
def rodar_dia(con, dia: date, agora: datetime, cache_codigo: dict, *,
              symbol: str = SIMBOLO, dia_encerrado: bool = False) -> list[dict]:
    """O papel do dia de cada ligação, calculado — sem gravar.

    Separado de `gravar` porque a captura calcula fora da conexão de
    escrita (spec §4.4.6): o motor não pode segurar a trava do banco.
    Cada resultado: `ligacao_id, dia, plano_id, codigo_hash, motor_versao,
    status, motivo, interrompido_em, operacoes` — `operacoes = None` quer
    dizer "não mexa no que está gravado". Pregão congelado não aparece.

    Pregão `interrompido` (código mudou no meio, decisão 5) guarda o que
    tinha, como estava: uma operação aberta naquele minuto continua
    `aberta` no banco, com o resultado provisório, e não entra no
    `liquido` do pregão.
    """
    if not _tem_candle(con, symbol, dia):
        return []
    gravados = {r[0]: {"status": r[1], "codigo_hash": r[2]}
                for r in con.execute(
                    "SELECT ligacao_id, status, codigo_hash FROM papel_pregoes "
                    "WHERE dia = ?", [dia]).fetchall()}
    com_ops = {r[0] for r in con.execute(
        "SELECT DISTINCT ligacao_id FROM papel_operacoes WHERE dia = ?",
        [dia]).fetchall()}
    resultados: list[dict] = []
    fila: list[tuple[dict, dict, dict]] = []      # (resultado, ligação, plano)
    planos: dict[int, tuple[dict, object]] = {}   # plano_id -> (plano, módulo)

    for l in ligacoes_do_papel(con, symbol, dia):
        lig = l["ligacao_id"]
        antes = gravados.get(lig)
        if antes and antes["status"] in CONGELADOS:
            continue
        r = {"ligacao_id": lig, "dia": dia, "plano_id": l["plano_id"],
             "codigo_hash": None, "motor_versao": engine.VERSAO,
             "status": "rodando", "motivo": None, "interrompido_em": None,
             "operacoes": None}
        resultados.append(r)
        try:
            if l["plano_id"] is None:
                r.update(status="pulado", motivo="sem plano em vigor")
                continue
            p = _plano.detalhes(l["plano_id"], con=con)
            estrategia = p["strategy"] or l["estrategia"]
            hash_disco = codigo.hash_estrategia(estrategia)
            r["codigo_hash"] = hash_disco
            # o hash de referência é o do plano; plano antigo (sem hash)
            # usa o do código que começou o pregão — mudar no meio do dia
            # interrompe do mesmo jeito (decisão 5)
            do_dia = antes and antes["codigo_hash"]
            if hash_disco is None:
                motivo = "código da estratégia não encontrado"
            elif p["codigo_hash"] and p["codigo_hash"] != hash_disco:
                motivo = "código mudou desde o plano"
            elif (not p["codigo_hash"] and do_dia and do_dia != hash_disco
                  and lig in com_ops):
                # só com operação gravada: sem ela nada foi calculado com o
                # código antigo, e o novo pode começar o pregão
                motivo = "código mudou no meio do pregão"
            else:
                motivo = None
            if motivo:
                if lig in com_ops:
                    # o que já foi gravado fica: é o que a variante fez com
                    # o código aprovado. Daqui para frente não há papel —
                    # inclusive uma operação que estava ABERTA fica aberta,
                    # com o resultado provisório da última volta (decisão
                    # 5): fechá-la exigiria rodar o código que mudou. A
                    # conferência também não a toca (pregão congelado).
                    r.update(status="interrompido", interrompido_em=agora,
                             codigo_hash=do_dia or p["codigo_hash"],
                             motivo=("código mudou no meio do pregão"
                                     if hash_disco else motivo))
                else:
                    r.update(status="pulado", motivo=motivo)
                continue
            if not p["codigo_hash"]:
                r["motivo"] = "plano sem impressão do código"
            if l["plano_id"] not in planos:
                planos[l["plano_id"]] = (p, _modulo(estrategia, hash_disco,
                                                    cache_codigo))
            fila.append((r, l, p))
        except Exception as erro:          # uma ligação não derruba as outras
            log.exception("papel: ligação #%s no dia %s", lig, dia)
            # o hash do pregão continua o do código que de fato calculou
            r.update(status=antes["status"] if antes else "rodando",
                     codigo_hash=antes["codigo_hash"] if antes else None,
                     motivo=f"falha no cálculo: {erro}", operacoes=None)

    if not fila:
        return resultados

    # Barras uma vez por volta, com o maior aquecimento entre as ligações.
    # Plano com parâmetro quebrado falha aqui, mas só para as ligações dele
    # (spec §4.6): a falha fica guardada e é levantada dentro do `try` de
    # cada ligação, como qualquer outra falha de cálculo.
    falhas: dict[int, Exception] = {}
    aquecimento = 0
    for pid, (p, mod) in planos.items():
        try:
            estrat, perfil = perfil_do_plano(p)
            aquecimento = max(aquecimento,
                              pregoes_de_aquecimento(mod, estrat, perfil))
        except Exception as erro:
            falhas[pid] = erro
    barras = inst = comum = None
    try:
        barras = barras_do_dia(con, symbol, dia, aquecimento)
        inst = db.load_instrument_yaml(symbol)
    except Exception as erro:
        comum = erro
    fech = FECHAMENTO_DIA_ENCERRADO if dia_encerrado else None

    calculados: dict[int, list[dict]] = {}
    for r, l, p in fila:
        pid = l["plano_id"]
        try:
            if pid in falhas:
                raise falhas[pid]
            if comum is not None:
                raise comum
            if pid not in calculados:
                # mesma variante em dois portfólios: o mesmo plano roda
                # uma vez só e vale para as duas ligações
                calculados[pid] = calcular(barras, dia, p, planos[pid][1],
                                           inst, fech)
            periodos = periodos_ligados(con, l["ligacao_id"],
                                        l["portfolio_id"], dia)
            r["operacoes"] = [{**o, "conta": _conta(o["entry_ts"], periodos)}
                              for o in calculados[pid]]
        except Exception as erro:
            log.exception("papel: ligação #%s no dia %s", l["ligacao_id"], dia)
            antes = gravados.get(l["ligacao_id"])
            r.update(status=antes["status"] if antes else "rodando",
                     motivo=f"falha no cálculo: {erro}", operacoes=None)
    return resultados


_CAMPOS_OP = ("exit_ts", "side", "contratos", "entry_px", "exit_px", "points",
              "bruto", "custo", "liquido", "reason", "mae", "mfe", "stop_px",
              "alvo_px", "aberta", "conta")


def _gravar(con, resultados: list[dict], agora: datetime) -> None:
    for r in resultados:
        lig, dia = r["ligacao_id"], r["dia"]
        atual = con.execute("SELECT status FROM papel_pregoes WHERE "
                            "ligacao_id = ? AND dia = ?", [lig, dia]).fetchone()
        if atual and atual[0] in CONGELADOS:
            continue          # congelou entre o cálculo e a gravação
        ops = r.get("operacoes")
        if ops is not None:
            existentes = {row[0]: (row[1], list(row[2:])) for row in con.execute(
                f"SELECT entry_ts, op_id, plano_id, {', '.join(_CAMPOS_OP)} "
                "FROM papel_operacoes WHERE ligacao_id = ? AND dia = ?",
                [lig, dia]).fetchall()}
            novas = sorted(ops, key=lambda o: o["entry_ts"])
            for o in novas:
                valores = [o[c] for c in _CAMPOS_OP]
                op_id, antigos = existentes.get(o["entry_ts"], (None, None))
                if op_id is not None:
                    if antigos == [r["plano_id"], *valores]:
                        # fechada e igual: não regrava. A cada minuto só a
                        # aberta muda, e a trava do banco é da captura
                        continue
                    # a mesma operação recalculada é a MESMA linha: o op_id
                    # é o que a parte 4 usa para ligar a ordem real a ela
                    con.execute(
                        f"UPDATE papel_operacoes SET plano_id = ?, "
                        f"{', '.join(c + ' = ?' for c in _CAMPOS_OP)}, "
                        "calculado_em = ? WHERE op_id = ?",
                        [r["plano_id"], *valores, agora, op_id])
                else:
                    con.execute(
                        "INSERT INTO papel_operacoes (op_id, ligacao_id, "
                        f"plano_id, dia, entry_ts, {', '.join(_CAMPOS_OP)}, "
                        "calculado_em) VALUES (nextval('seq_papel_op'), "
                        f"?, ?, ?, ?, {', '.join('?' * len(_CAMPOS_OP))}, ?)",
                        [lig, r["plano_id"], dia, o["entry_ts"], *valores,
                         agora])
            # só some com candle corrigido: a operação deixou de existir
            vivas = {o["entry_ts"] for o in novas}
            sumiram = [i for ts, (i, _) in existentes.items()
                       if ts not in vivas]
            if sumiram:
                con.execute(
                    "DELETE FROM papel_operacoes WHERE op_id IN "
                    f"({', '.join('?' * len(sumiram))})", sumiram)
        n, liquido = con.execute(
            "SELECT count(*), coalesce(sum(liquido) FILTER "
            "(WHERE conta AND NOT aberta), 0) FROM papel_operacoes "
            "WHERE ligacao_id = ? AND dia = ?", [lig, dia]).fetchone()
        con.execute(
            "INSERT INTO papel_pregoes (ligacao_id, dia, plano_id, "
            "codigo_hash, motor_versao, status, motivo, interrompido_em, "
            "n_operacoes, liquido, calculado_em) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (ligacao_id, dia) DO UPDATE SET "
            "plano_id = excluded.plano_id, "
            "codigo_hash = coalesce(excluded.codigo_hash, "
            "                      papel_pregoes.codigo_hash), "
            "motor_versao = excluded.motor_versao, status = excluded.status, "
            "motivo = excluded.motivo, "
            "interrompido_em = excluded.interrompido_em, "
            "n_operacoes = excluded.n_operacoes, "
            "liquido = excluded.liquido, calculado_em = excluded.calculado_em",
            [lig, dia, r["plano_id"], r["codigo_hash"], r["motor_versao"],
             r["status"], r["motivo"], r["interrompido_em"], int(n),
             float(liquido), agora])


def gravar(con, resultados: list[dict], agora: datetime) -> None:
    """Grava o que `rodar_dia` calculou, numa transação só: o papel de todas
    as ligações entra junto ou não entra (spec §4.4.5–6).

    Upsert por `(ligacao_id, entry_ts)`: a operação nova ganha `op_id` da
    sequência, a recalculada atualiza a própria linha — nunca apagar e
    reinserir, que trocaria o número. `liquido` do pregão soma só as
    fechadas que contam: a aberta é provisória até fechar.
    """
    if not resultados:
        return
    with db.transacao(con):
        _gravar(con, resultados, agora)


def conferir(con, dia: date, agora: datetime, cache_codigo: dict, *,
             symbol: str = SIMBOLO) -> list[dict]:
    """A última volta do dia, depois da conferência dos candles.

    Recalcula com o dia encerrado (a última barra é o fechamento real: nada
    fica aberto, nem num pregão que fechou cedo), grava o checksum das
    barras e congela o pregão. Depois disso, candle corrigido não muda o
    papel — acusa divergência (decisão 6, `divergencias`).
    """
    res = rodar_dia(con, dia, agora, cache_codigo, symbol=symbol,
                    dia_encerrado=True)
    if not res:
        return res
    soma = checksum(con, symbol, dia)
    # falha no cálculo não congela: sem operações recalculadas o dia não foi
    # conferido, e a próxima janela tenta de novo
    rodando = [r["ligacao_id"] for r in res
               if r["status"] == "rodando" and r["operacoes"] is not None]
    with db.transacao(con):
        _gravar(con, res, agora)
        if rodando:
            con.execute(
                "UPDATE papel_pregoes SET status = 'conferido', checksum = ? "
                f"WHERE dia = ? AND status = 'rodando' AND ligacao_id IN "
                f"({', '.join('?' * len(rodando))})", [soma, dia, *rodando])
    for r in res:
        if r["ligacao_id"] in rodando:
            r["status"] = "conferido"
    return res


def divergencias(con, symbol: str = SIMBOLO,
                 ligacoes=None) -> list[dict]:
    """Pregões conferidos cujos candles mudaram depois: o papel gravado foi
    calculado sobre outras barras. Aviso para a tela e para o auditor.

    `ligacoes` restringe a busca (a tela olha um portfólio). As impressões
    saem numa consulta só, agrupada por dia, com a mesma conta de
    `checksum` — a tela relê isto a cada volta da captura, e uma varredura
    das barras por pregão conferido crescia com o histórico do papel.
    """
    filtro, args = "", []
    if ligacoes is not None:
        ligacoes = list(ligacoes)
        if not ligacoes:
            return []
        filtro = f" AND pp.ligacao_id IN ({', '.join('?' * len(ligacoes))})"
        args = ligacoes
    linhas = con.execute(
        "SELECT pp.ligacao_id, pp.dia, pp.checksum FROM papel_pregoes pp "
        "JOIN planos_operacao p ON p.plano_id = pp.plano_id "
        f"WHERE pp.status = 'conferido' AND p.symbol = ?{filtro} "
        "ORDER BY pp.dia, pp.ligacao_id", [symbol, *args]).fetchall()
    if not linhas:
        return []
    dias = sorted({r[1] for r in linhas})
    ini, fim = _limites(dias[0])[0], _limites(dias[-1])[1]
    agrupado = {r[0]: ":".join(str(int(x or 0)) for x in r[1:])
                for r in con.execute(
                    "SELECT CAST(ts AS DATE), count(*), sum(open), sum(high), "
                    "sum(low), sum(close) FROM bars_m1 WHERE symbol = ? "
                    "AND ts >= ? AND ts < ? GROUP BY CAST(ts AS DATE)",
                    [symbol, ini, fim]).fetchall()}
    atuais = {d: agrupado.get(d, "0:0:0:0:0") for d in dias}
    out = []
    for lig, dia, gravado in linhas:
        if gravado != atuais[dia]:
            out.append({"ligacao_id": lig, "dia": dia, "gravado": gravado,
                        "atual": atuais[dia]})
    return out
