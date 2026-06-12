"""Rotas REST v1 — contratos em docs/02-arquitetura.md §3."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src import approvals as approvals_gate
from src.api import schemas
from src.api.deps import MonitorRunner, get_db, get_monitor_runner
from src.db.models import AgentRun, Alert, Approval

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


@router.get("/runs/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, detail=f"run {run_id} não existe")
    return run
