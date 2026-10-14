"""Conferência diária papel × backtest (spec ao-vivo-ordens §8).

O papel promete ser o backtest (decisão 1): mesmo motor, mesmos candles,
mesma montagem de perfil. Esta conferência é o que transforma a promessa em
fato verificado: toda manhã, depois da reconferência dos candles, roda o
backtest do plano sobre o histórico INTEIRO até o fim do dia e compara com
o papel gravado, operação por operação. O selo "papel = backtest ✓" da tela
e a trava de promoção para a demo saem daqui.

Por que o histórico inteiro, e não as barras de aquecimento do papel: é a
pergunta que o usuário fez — "o ao vivo é o backtest?". Rodar com o mesmo
recorte do papel só provaria que o papel é igual a si mesmo; um aquecimento
curto demais (`papel.pregoes_de_aquecimento`) passaria despercebido.

Nada aqui importa Dash; quem chama é a captura, com a conexão de escrita,
fora do pregão (o backtest do histórico inteiro custa segundos).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np

from . import codigo
from . import db_manager as db
from . import engine
from . import papel
from . import plano as _plano
from .captura import PREFIXO_RECONFERENCIA
from .engine.execution import prepare_bars, run_strategy


def _tupla_papel(r) -> tuple:
    entry_ts, side, entry_px, exit_ts, exit_px, reason = r
    return (entry_ts, int(side), int(entry_px), exit_ts,
            None if exit_px is None else int(exit_px),
            None if reason is None else int(reason))


def _backtest(con, plano: dict, mod, dia: date, symbol: str) -> list[tuple]:
    """As operações do backtest com entrada no `dia`, no formato da tupla de
    comparação. Mesmo módulo que o papel carrega (`papel._modulo`, pelo
    código do disco) e mesmo perfil (`papel.perfil_do_plano` — nunca
    `ExecutionProfile.from_config`, que devolveria o perfil padrão)."""
    estrat, perfil = papel.perfil_do_plano(plano)
    # do BANCO, não do Parquet: o dia conferido só chega ao espelho depois,
    # e o espelho atrasado cortaria o histórico antes do dia
    fim = datetime.combine(dia + timedelta(days=1), datetime.min.time())
    barras = prepare_bars(con, symbol, end=fim - timedelta(microseconds=1))
    if not len(barras["ts"]):
        return []
    # sem `vela_aberta`: o dia acabou, a última vela fechou com ele
    res = run_strategy(barras, mod, estrat, perfil,
                       db.load_instrument_yaml(symbol))
    if res.n_trades == 0:
        return []
    t = res.trades
    no_dia = np.flatnonzero(t["entry_ts"].astype("datetime64[D]")
                            == np.datetime64(dia, "D"))
    return [(papel._dt(t["entry_ts"][i]), int(t["side"][i]),
             int(t["entry_px"][i]), papel._dt(t["exit_ts"][i]),
             int(t["exit_px"][i]), int(t["reason"][i])) for i in no_dia]


def _json(diferencas: list[dict], checksum_mudou: bool) -> str:
    def iso(x):
        return x.isoformat(sep=" ") if isinstance(x, datetime) else x
    return json.dumps({
        "checksum_mudou": checksum_mudou,
        "operacoes": [{"entry_ts": iso(d["entry_ts"]),
                       "papel": None if d["papel"] is None
                       else [iso(x) for x in d["papel"]],
                       "backtest": None if d["backtest"] is None
                       else [iso(x) for x in d["backtest"]]}
                      for d in diferencas]})


def _incomparavel(motor, hash_dia, estrategia, hashes: dict) -> str | None:
    """Por que o papel gravado NÃO é comparável com o backtest de hoje, ou
    None se é. Motor de outra versão ou código da estratégia diferente do
    que está no disco: o backtest rodaria outro cálculo, e a diferença seria
    da mudança, não do papel — a mesma régua de `papel.reabriveis`, que
    pelos mesmos motivos não reabre esses pregões. `hashes` guarda o hash
    de cada estratégia (ler o arquivo uma vez por chamada)."""
    if motor != engine.VERSAO:
        return "outra_versao"
    if estrategia not in hashes:
        hashes[estrategia] = codigo.hash_estrategia(estrategia)
    if hash_dia is None or hash_dia != hashes[estrategia]:
        return "outro_codigo"
    return None


def conferir(con, ligacao_id: int, dia: date, cache_codigo: dict,
             agora: datetime, *, symbol: str = papel.SIMBOLO) -> dict:
    """Compara o papel conferido do dia com o backtest e grava o resultado
    em `papel_backtest` (upsert por ligação e dia).

    Entram só as operações que CONTAM: no papel, `conta`; no backtest, as
    com entrada nos mesmos `papel.periodos_ligados` — a ligação desligada
    às 11h não fez o que entrou depois, nem num lado nem no outro.

    Papel de outra versão do motor ou de outro código da estratégia
    (`papel_pregoes.motor_versao` / `codigo_hash`) não é comparável: volta
    `ok = None` com `outra_versao` ou `outro_codigo` verdadeiro e não grava
    nada — uma falha gravada travaria a promoção para sempre (`situacao`)
    por uma mudança feita de propósito.

    `checksum_mudou`: os candles do dia não são mais os que o papel usou
    (`papel_pregoes.checksum` da conferência). A diferença, se houver, vem
    daí — vai junto no JSON para a tela dizer.
    """
    r = con.execute(
        "SELECT pm.portfolio_id, ev.estrategia, pp.plano_id, pp.status, "
        "pp.motor_versao, pp.codigo_hash, pp.checksum "
        "FROM portfolio_membros pm "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "LEFT JOIN papel_pregoes pp ON pp.ligacao_id = pm.ligacao_id "
        "     AND pp.dia = ? "
        "WHERE pm.ligacao_id = ?", [dia, ligacao_id]).fetchone()
    if r is None:
        raise ValueError(f"ligação #{ligacao_id} não existe")
    portfolio_id, est_variante, plano_id, status, motor, hash_dia, soma = r
    if status != "conferido" or plano_id is None:
        # comparar um pregão ainda vivo (ou sem plano) acusaria diferença
        # que não existe: o papel dele ainda vai mudar
        raise ValueError(f"pregão {dia} da ligação #{ligacao_id} "
                         "não está conferido")
    papel_ops = [_tupla_papel(x) for x in con.execute(
        "SELECT entry_ts, side, entry_px, exit_ts, exit_px, reason "
        "FROM papel_operacoes WHERE ligacao_id = ? AND dia = ? AND conta "
        "ORDER BY entry_ts", [ligacao_id, dia]).fetchall()]
    plano = _plano.detalhes(plano_id, con=con)
    # plano antigo pode não ter a estratégia gravada: vale a da variante
    # (mesma regra de `papel.preparar_dia`)
    estrategia = plano["strategy"] or est_variante
    out = {"ok": None, "n_papel": len(papel_ops), "n_backtest": 0,
           "diferencas": [], "checksum_mudou": False,
           "outra_versao": False, "outro_codigo": False}
    hashes: dict = {}
    motivo = _incomparavel(motor, hash_dia, estrategia, hashes)
    if motivo:
        out[motivo] = True
        return out

    mod = papel._modulo(estrategia, hashes[estrategia], cache_codigo)
    periodos = papel.periodos_ligados(con, ligacao_id, portfolio_id, dia)
    bt_ops = [o for o in _backtest(con, plano, mod, dia, symbol)
              if papel._conta(o[0], periodos)]

    do_papel = {o[0]: o for o in papel_ops}
    do_bt = {o[0]: o for o in bt_ops}
    diferencas = [{"entry_ts": ts, "papel": do_papel.get(ts),
                   "backtest": do_bt.get(ts)}
                  for ts in sorted(do_papel.keys() | do_bt.keys())
                  if do_papel.get(ts) != do_bt.get(ts)]
    out.update(ok=not diferencas, n_backtest=len(bt_ops),
               diferencas=diferencas,
               checksum_mudou=soma != papel.checksum(con, symbol, dia))
    con.execute(
        "INSERT INTO papel_backtest (ligacao_id, dia, conferido_em, ok, "
        "n_papel, n_backtest, diferencas) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT (ligacao_id, dia) DO UPDATE SET "
        "conferido_em = excluded.conferido_em, ok = excluded.ok, "
        "n_papel = excluded.n_papel, n_backtest = excluded.n_backtest, "
        "diferencas = excluded.diferencas",
        [ligacao_id, dia, agora, out["ok"], out["n_papel"], out["n_backtest"],
         _json(diferencas, out["checksum_mudou"])])
    return out


def pendentes(con, symbol: str = papel.SIMBOLO) -> list[tuple[int, date]]:
    """Os `(ligacao_id, dia)` que a manhã ainda precisa conferir.

    Só depois da reconferência do dia (marca `reconferencia://<dia>` no
    ingest_log): antes dela os candles do fechamento ainda vão mudar (o
    leilão entra no 18:24 de madrugada) e o backtest compararia o papel
    contra um dia que ainda não é o final.

    Quem chama roda ANTES `papel.reabrir_reconferido` + `papel.conferir` do
    dia: o papel tem de estar refeito nos candles finais. Mesmo assim, a
    checagem gravada só vale se for posterior à reconferência E ao último
    cálculo do papel (`papel_pregoes.calculado_em`): papel refeito depois
    dela faz a checagem falar de um papel que não existe mais, e o pregão
    volta à fila. As horas são todas do relógio da captura
    (`source_max_ts`, `calculado_em`, o `agora` de `conferir`).

    Papel de outra versão do motor ou de outro código fica de fora (ver
    `conferir`).
    """
    linhas = con.execute(
        "WITH reconf AS ("
        "  SELECT source_file, max(source_max_ts) AS quando FROM ingest_log "
        "  WHERE symbol = ? AND source_file LIKE ? GROUP BY source_file) "
        "SELECT pp.ligacao_id, pp.dia, pp.motor_versao, pp.codigo_hash, "
        "coalesce(p.strategy, ev.estrategia) FROM papel_pregoes pp "
        "JOIN planos_operacao p ON p.plano_id = pp.plano_id "
        "JOIN portfolio_membros pm ON pm.ligacao_id = pp.ligacao_id "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "JOIN reconf r ON r.source_file = ? || strftime(pp.dia, '%Y-%m-%d') "
        "LEFT JOIN papel_backtest pb ON pb.ligacao_id = pp.ligacao_id "
        "     AND pb.dia = pp.dia "
        "WHERE pp.status = 'conferido' AND p.symbol = ? "
        "  AND (pb.conferido_em IS NULL "
        "       OR pb.conferido_em < greatest(r.quando, pp.calculado_em)) "
        "ORDER BY pp.dia, pp.ligacao_id",
        [symbol, f"{PREFIXO_RECONFERENCIA}%", PREFIXO_RECONFERENCIA,
         symbol]).fetchall()
    hashes: dict = {}
    return [(int(lig), d) for lig, d, motor, hash_dia, estrategia in linhas
            if _incomparavel(motor, hash_dia, estrategia, hashes) is None]


def situacao(con, ligacao_id: int) -> dict:
    """O selo da Avaliação: quantos pregões e operações já foram conferidos
    contra o backtest, quantas diferenças, e se está tudo igual (`ok`;
    `None` = nenhum pregão conferido ainda).

    `outra_versao` / `outro_codigo`: pregões conferidos com outro motor ou
    outro código da estratégia e sem conferência gravada — não contam nem a
    favor nem contra (ver `conferir`).
    """
    pregoes, operacoes, diferencas, ok = con.execute(
        "SELECT count(*), coalesce(sum(n_papel), 0), "
        "coalesce(sum(json_array_length(diferencas, '$.operacoes')), 0), "
        "bool_and(ok) FROM papel_backtest WHERE ligacao_id = ?",
        [ligacao_id]).fetchone()
    linhas = con.execute(
        "SELECT pp.motor_versao, pp.codigo_hash, "
        "coalesce(p.strategy, ev.estrategia) FROM papel_pregoes pp "
        "JOIN planos_operacao p ON p.plano_id = pp.plano_id "
        "JOIN portfolio_membros pm ON pm.ligacao_id = pp.ligacao_id "
        "JOIN estrategia_variantes ev ON ev.variante_id = pm.variante_id "
        "LEFT JOIN papel_backtest pb ON pb.ligacao_id = pp.ligacao_id "
        "     AND pb.dia = pp.dia "
        "WHERE pp.ligacao_id = ? AND pp.status = 'conferido' "
        "  AND pb.dia IS NULL", [ligacao_id]).fetchall()
    hashes: dict = {}
    motivos = [_incomparavel(m, h, e, hashes) for m, h, e in linhas]
    return {"pregoes": int(pregoes), "operacoes": int(operacoes),
            "diferencas": int(diferencas),
            "ok": None if not pregoes else bool(ok),
            "outra_versao": motivos.count("outra_versao"),
            "outro_codigo": motivos.count("outro_codigo")}
