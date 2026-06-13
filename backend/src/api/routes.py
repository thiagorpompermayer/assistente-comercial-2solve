"""Rotas REST v1 — contratos em docs/02-arquitetura.md §3."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src import approvals as approvals_gate
from src.api import schemas
from src.api.deps import (
    CrmRunner,
    EmailRunner,
    MonitorRunner,
    ProposalRunner,
    get_crm_runner,
    get_db,
    get_email_runner,
    get_graph_client,
    get_monitor_runner,
    get_proposal_runner,
)
from src.connectors.ms365 import GraphClient, GraphError
from src.db.models import AgentRun, Alert, Approval, EmailTriaged, Proposal

router = APIRouter()

# ----- saúde -----


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


# ----- alertas (Etapa 2) -----


@router.get("/alerts", response_model=list[schemas.AlertOut])
def list_alerts(
    status: str | None = "open",
    kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(Alert.status == status)
    if kind:
        query = query.where(Alert.kind == kind)
    return list(db.scalars(query))


@router.patch("/alerts/{alert_id}", response_model=schemas.AlertOut)
def patch_alert(
    alert_id: int, body: schemas.AlertPatch, db: Session = Depends(get_db)
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, detail=f"alerta {alert_id} não existe")
    alert.status = body.status
    db.commit()
    return alert


# ----- aprovações (transversal) -----


@router.get("/approvals", response_model=list[schemas.ApprovalOut])
def list_approvals(
    status: str | None = "pending",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Approval]:
    query = (
        select(Approval).order_by(Approval.requested_at.desc()).limit(limit).offset(offset)
    )
    if status:
        query = query.where(Approval.status == status)
    return list(db.scalars(query))


@router.get("/approvals/{approval_id}", response_model=schemas.ApprovalOut)
def get_approval(approval_id: int, db: Session = Depends(get_db)) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, detail=f"approval {approval_id} não existe")
    return approval


@router.post("/approvals/{approval_id}/approve", response_model=schemas.ApprovalOut)
def approve_action(
    approval_id: int, body: schemas.DecisionIn, db: Session = Depends(get_db)
) -> Approval:
    try:
        return approvals_gate.approve(db, approval_id, decided_by=body.decided_by)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except approvals_gate.ApprovalStateError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/approvals/{approval_id}/reject", response_model=schemas.ApprovalOut)
def reject_action(
    approval_id: int, body: schemas.DecisionIn, db: Session = Depends(get_db)
) -> Approval:
    try:
        return approvals_gate.reject(
            db, approval_id, decided_by=body.decided_by, reason=body.reason
        )
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except approvals_gate.ApprovalStateError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


# ----- emails (Etapa 3) -----


@router.get("/emails/triaged", response_model=list[schemas.EmailTriagedOut])
def list_triaged_emails(
    classification: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[EmailTriaged]:
    query = (
        select(EmailTriaged)
        .order_by(EmailTriaged.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if classification:
        query = query.where(EmailTriaged.classification == classification)
    return list(db.scalars(query))


@router.get("/emails/{triage_id}/draft", response_model=schemas.DraftOut)
def get_email_draft(
    triage_id: int,
    db: Session = Depends(get_db),
    graph: GraphClient = Depends(get_graph_client),
) -> schemas.DraftOut:
    row = db.get(EmailTriaged, triage_id)
    if row is None:
        raise HTTPException(404, detail=f"email triado {triage_id} não existe")
    if not row.draft_id:
        raise HTTPException(404, detail=f"email triado {triage_id} não tem rascunho")
    try:
        draft = graph.get_message(row.draft_id)
    except GraphError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    return schemas.DraftOut(
        draft_id=row.draft_id,
        subject=draft.get("subject"),
        body=(draft.get("body") or {}).get("content", ""),
        to=[
            r["emailAddress"]["address"]
            for r in draft.get("toRecipients", [])
            if r.get("emailAddress", {}).get("address")
        ],
    )


@router.post("/agents/email/triage", response_model=schemas.RunAccepted, status_code=202)
def run_email_triage(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    runner: EmailRunner = Depends(get_email_runner),
) -> schemas.RunAccepted:
    run = AgentRun(agent="email", trigger="api", status="queued")
    db.add(run)
    db.commit()
    background.add_task(runner, run.id)
    return schemas.RunAccepted(run_id=run.id, status="queued")


# ----- propostas (Etapa 4) -----


@router.post("/proposals", response_model=schemas.ProposalAccepted, status_code=202)
def create_proposal(
    body: schemas.ProposalIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    runner: ProposalRunner = Depends(get_proposal_runner),
) -> schemas.ProposalAccepted:
    proposal = Proposal(
        omie_client_id=body.omie_client_id,
        title=body.title,
        input_json=body.model_dump(),
        status="draft",
    )
    run = AgentRun(agent="proposal", trigger="api", status="queued")
    db.add_all([proposal, run])
    db.commit()
    proposal.run_id = run.id
    db.commit()
    background.add_task(runner, proposal.id, run.id)
    return schemas.ProposalAccepted(
        proposal_id=proposal.id, run_id=run.id, status="queued"
    )


@router.get("/proposals", response_model=list[schemas.ProposalOut])
def list_proposals(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Proposal]:
    query = (
        select(Proposal).order_by(Proposal.created_at.desc()).limit(limit).offset(offset)
    )
    if status:
        query = query.where(Proposal.status == status)
    return list(db.scalars(query))


@router.get("/proposals/{proposal_id}", response_model=schemas.ProposalOut)
def get_proposal(proposal_id: int, db: Session = Depends(get_db)) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, detail=f"proposta {proposal_id} não existe")
    return proposal


@router.get("/proposals/{proposal_id}/download")
def download_proposal(proposal_id: int, db: Session = Depends(get_db)) -> FileResponse:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, detail=f"proposta {proposal_id} não existe")
    if not proposal.pptx_path or not Path(proposal.pptx_path).exists():
        raise HTTPException(404, detail=f"proposta {proposal_id} ainda não tem PPTX gerado")
    path = Path(proposal.pptx_path)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml"
        ".presentation",
    )


# ----- agentes -----


@router.post("/agents/monitor/run", response_model=schemas.RunAccepted, status_code=202)
def run_monitor(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    runner: MonitorRunner = Depends(get_monitor_runner),
) -> schemas.RunAccepted:
    run = AgentRun(agent="monitor", trigger="api", status="queued")
    db.add(run)
    db.commit()
    background.add_task(runner, run.id)
    return schemas.RunAccepted(run_id=run.id, status="queued")


@router.post("/agents/crm/run", response_model=schemas.RunAccepted, status_code=202)
def run_crm(
    body: schemas.CrmDemandIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    runner: CrmRunner = Depends(get_crm_runner),
) -> schemas.RunAccepted:
    run = AgentRun(agent="crm", trigger="api", status="queued")
    db.add(run)
    db.commit()
    background.add_task(runner, body.demand, run.id)
    return schemas.RunAccepted(run_id=run.id, status="queued")


@router.get("/runs/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, detail=f"run {run_id} não existe")
    return run
