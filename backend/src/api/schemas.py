"""Schemas pydantic — fonte da verdade do contrato REST v1 (regra dura: API é contrato)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    kind: str
    entity_ref: str | None
    title: str
    detail: str
    severity: str
    status: str
    created_at: datetime


class AlertPatch(BaseModel):
    status: Literal["open", "dismissed", "done"]


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    action_type: str
    payload_json: dict[str, Any]
    preview_text: str
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    reject_reason: str | None
    executed_at: datetime | None
    error: str | None


class DecisionIn(BaseModel):
    # Fallback até a autenticação entrar (Etapa 3) — depois vem do token JWT.
    decided_by: str
    reason: str | None = None


class EmailTriagedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    graph_message_id: str
    sender: str | None
    subject: str | None
    received_at: str | None
    classification: str
    summary: str
    draft_id: str | None
    created_at: datetime


class DraftOut(BaseModel):
    draft_id: str
    subject: str | None
    body: str
    to: list[str]


class ProposalItemIn(BaseModel):
    descricao: str
    quantidade: float = 1
    unidade: str = "UN"
    valor_unitario: float | None = None


class ProposalIn(BaseModel):
    omie_client_id: int | None = None
    cliente: str
    projeto: str
    title: str
    scope: list[str] = []
    items: list[ProposalItemIn] = []
    deadline: str = "A combinar"
    conditions: list[str] = []
    notes: list[str] = []
    seller: str = ""


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    omie_client_id: int | None
    title: str
    input_json: dict[str, Any]
    pptx_path: str | None
    onedrive_url: str | None
    status: str
    created_at: datetime


class ProposalAccepted(BaseModel):
    proposal_id: int
    run_id: int
    status: str


class RunAccepted(BaseModel):
    run_id: int
    status: str


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    trigger: str
    status: str
    error: str | None
    tokens_in: int
    tokens_out: int
    started_at: datetime
    finished_at: datetime | None
