"""Agregações do dashboard (comercial + operação) e sync do pipeline.

As funções de resumo leem SOMENTE o banco local (pipeline_cache + tabelas dos
agentes) — rodam offline, sem credencial, e por isso são testáveis e rápidas
(risco R1: o dashboard nunca bate no Omie ao vivo). O sync é o único ponto que
fala com o Omie, acionado por job agendado ou endpoint manual.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.connectors.omie import OmieClient
from src.db.models import (
    AgentRun,
    Alert,
    Approval,
    EmailTriaged,
    PipelineCache,
    Proposal,
    utcnow,
)


def pipeline_summary(session: Session) -> dict[str, Any]:
    """Pipeline comercial por estágio (valor e quantidade) + ticket médio."""
    rows = session.execute(
        select(
            PipelineCache.etapa,
            func.count(PipelineCache.id),
            func.coalesce(func.sum(PipelineCache.valor), 0.0),
        ).group_by(PipelineCache.etapa)
    ).all()

    stages = [
        {"etapa": etapa, "quantidade": qtd, "valor_total": round(float(total), 2)}
        for etapa, qtd, total in rows
    ]
    stages.sort(key=lambda s: s["valor_total"], reverse=True)
    total_qtd = sum(s["quantidade"] for s in stages)
    total_valor = round(sum(s["valor_total"] for s in stages), 2)
    ticket_medio = round(total_valor / total_qtd, 2) if total_qtd else 0.0

    last_sync = session.scalar(select(func.max(PipelineCache.synced_at)))
    return {
        "estagios": stages,
        "total_oportunidades": total_qtd,
        "valor_total": total_valor,
        "ticket_medio": ticket_medio,
        "sincronizado_em": last_sync.isoformat() if last_sync else None,
    }


def operations_summary(session: Session, days: int = 30) -> dict[str, Any]:
    """Métricas operacionais do assistente na janela recente."""
    since = utcnow() - timedelta(days=days)

    def _count_by(column, model, **filters):  # type: ignore[no-untyped-def]
        stmt = select(column, func.count()).group_by(column)
        for attr, value in filters.items():
            stmt = stmt.where(getattr(model, attr) == value)
        return {str(k): v for k, v in session.execute(stmt).all()}

    approvals_by_status = _count_by(Approval.status, Approval)
    emails_recent = session.scalar(
        select(func.count()).select_from(EmailTriaged).where(EmailTriaged.created_at >= since)
    )

    return {
        "janela_dias": days,
        "emails_triados_periodo": int(emails_recent or 0),
        "emails_por_classificacao": _count_by(EmailTriaged.classification, EmailTriaged),
        "aprovacoes": {
            "fila_pendente": approvals_by_status.get("pending", 0),
            "executadas": approvals_by_status.get("executed", 0),
            "rejeitadas": approvals_by_status.get("rejected", 0),
            "falhas": approvals_by_status.get("failed", 0),
        },
        "alertas_abertos": session.scalar(
            select(func.count()).select_from(Alert).where(Alert.status == "open")
        ),
        "propostas_por_status": _count_by(Proposal.status, Proposal),
        "runs_por_agente": _count_by(AgentRun.agent, AgentRun),
    }


def _opp_field(record: dict[str, Any], *path_options: tuple[str, ...]) -> Any:
    """Extrai um campo de oportunidade Omie tolerando variações de estrutura."""
    for path in path_options:
        node: Any = record
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and node not in (None, ""):
            return node
    return None


def sync_pipeline_cache(session: Session, omie: OmieClient | None = None) -> dict[str, Any]:
    """Lê as oportunidades do Omie e atualiza o pipeline_cache (upsert por omie_id)."""
    omie = omie or OmieClient()

    # mapa código de etapa -> nome (defensivo: se falhar, usa o código)
    stage_names: dict[str, str] = {}
    try:
        stages = omie.list_opportunity_stages()
        for st in stages.get("cadastro", []) or stages.get("etapas", []) or []:
            code = str(st.get("nCodEtapa") or st.get("codigo") or "")
            name = st.get("cDescricao") or st.get("descricao") or ""
            if code and name:
                stage_names[code] = name
    except Exception:  # noqa: BLE001 — etapas são enriquecimento, não bloqueiam o sync
        stage_names = {}

    synced = 0
    page = 1
    now = datetime.now(timezone.utc)
    while True:
        data = omie.list_opportunities(page=page)
        records = data.get("cadastros") or data.get("oportunidades") or []
        for rec in records:
            omie_id = _opp_field(rec, ("identificacao", "nCodOp"), ("nCodOp",))
            if omie_id is None:
                continue
            omie_id = str(omie_id)
            code = _opp_field(rec, ("fasesStatus", "nCodFase"), ("nCodFase",))
            code_str = str(code) if code is not None else None
            etapa = stage_names.get(code_str or "", f"Etapa {code_str}" if code_str
                                    else "(sem etapa)")
            valor = _opp_field(rec, ("ticket", "nValorOp"), ("nValorOp",)) or 0.0
            titulo = _opp_field(rec, ("identificacao", "cDesOp"), ("cDesOp",))
            cliente = _opp_field(rec, ("identificacao", "nCodClien"), ("nCodClien",))

            row = session.scalar(select(PipelineCache).where(PipelineCache.omie_id == omie_id))
            if row is None:
                row = PipelineCache(omie_id=omie_id)
                session.add(row)
            row.titulo = titulo
            row.cliente_ref = str(cliente) if cliente is not None else None
            row.etapa = etapa
            row.etapa_codigo = code_str
            row.valor = float(valor)
            row.payload_json = rec
            row.synced_at = now
            synced += 1

        total_pages = int(data.get("total_de_paginas") or data.get("nTotPaginas") or 1)
        if page >= total_pages:
            break
        page += 1

    session.commit()
    return {"sincronizadas": synced, "paginas": page}
