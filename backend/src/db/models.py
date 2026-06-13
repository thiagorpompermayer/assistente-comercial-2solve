"""Modelos do banco — ver docs/02-arquitetura.md §2.

Campos *_json usam o tipo JSON do SQLAlchemy (portável SQLite → Postgres).
Timestamps sempre em UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AgentRun(Base):
    """Uma linha por execução de agente (via API, scheduler ou outro agente)."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(50), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="api")  # api|scheduler|agent
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="queued", index=True
    )  # queued|running|done|error
    error: Mapped[str | None] = mapped_column(Text, default=None)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AuditLog(Base):
    """REGRA DURA 3: toda chamada de ferramenta de agente grava aqui."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    is_write: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    """O portão de aprovação humana (regras duras 1 e 2).

    payload_json é EXATAMENTE o que será executado se aprovado — congelado
    no momento do pedido, nunca alterado depois.
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(50), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    preview_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending|approved|rejected|executed|failed
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    decided_by: Mapped[str | None] = mapped_column(String(100), default=None)
    reject_reason: Mapped[str | None] = mapped_column(Text, default=None)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class Alert(Base):
    """Saída do monitor_agent: atrasos e follow-ups pendentes."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(
        String(50), index=True
    )  # followup_overdue|proposal_stale|task_overdue
    entity_ref: Mapped[str | None] = mapped_column(String(100), default=None)  # id no Omie
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # low|medium|high
    status: Mapped[str] = mapped_column(
        String(20), default="open", index=True
    )  # open|dismissed|done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailTriaged(Base):
    """Saída do email_agent: um registro por email triado da caixa comercial."""

    __tablename__ = "emails_triaged"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    graph_message_id: Mapped[str] = mapped_column(String(255), index=True)
    sender: Mapped[str | None] = mapped_column(String(255), default=None)
    subject: Mapped[str | None] = mapped_column(String(500), default=None)
    received_at: Mapped[str | None] = mapped_column(String(50), default=None)  # ISO do Graph
    classification: Mapped[str] = mapped_column(
        String(30), index=True
    )  # lead|cliente_ativo|fornecedor|interno|irrelevante
    summary: Mapped[str] = mapped_column(Text, default="")
    draft_id: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Proposal(Base):
    """Saída do proposal_agent: uma proposta PPTX gerada (ou em geração)."""

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    omie_client_id: Mapped[int | None] = mapped_column(Integer, default=None)
    title: Mapped[str] = mapped_column(String(255))
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    pptx_path: Mapped[str | None] = mapped_column(String(500), default=None)
    onedrive_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", index=True
    )  # draft|generated|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EngineeringArtifact(Base):
    """Saída do engineering_agent: conteúdo técnico para propostas.

    Escrita LOCAL (não toca sistema externo) — livre, porém auditada.
    Pode ser vinculada a uma proposta para alimentar o proposal_agent.
    """

    __tablename__ = "engineering_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposals.id"), default=None, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(30), index=True
    )  # tag_analysis|instrument_list|flowchart|memorial
    title: Mapped[str] = mapped_column(String(255))
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    content_text: Mapped[str] = mapped_column(Text, default="")  # Mermaid ou Markdown
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionFlag(Base):
    """Liberação gradual de escrita externa, ação por ação (regra dura 2).

    Ausência de linha = auto_execute False. Deleções IGNORAM esta tabela:
    sempre exigem aprovação humana (regra dura 1).
    """

    __tablename__ = "action_flags"

    action_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(100), default=None)
