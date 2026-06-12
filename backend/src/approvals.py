"""Portão de aprovação humana — REGRAS DURAS 1 e 2 do CLAUDE.md.

Invariantes (testadas em tests/test_approvals.py):
1. O payload executado é exatamente o payload congelado no pedido.
2. Deleções (DELETE_ACTIONS) nunca auto-executam, mesmo com flag ligada.
3. Aprovar é idempotente: a transição approved→executed acontece uma vez.
4. Falha na execução marca `failed` com o erro — nunca silencia.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import ActionFlag, Approval, AuditLog, utcnow

DELETE_ACTIONS = frozenset({"email_delete", "omie_delete"})

Executor = Callable[[dict[str, Any]], dict[str, Any] | None]

_EXECUTORS: dict[str, Executor] = {}


class ApprovalStateError(RuntimeError):
    """Transição de estado inválida (ex.: aprovar algo já decidido)."""


def register_executor(action_type: str) -> Callable[[Executor], Executor]:
    """Registra a função que efetivamente executa uma ação aprovada."""

    def decorator(fn: Executor) -> Executor:
        _EXECUTORS[action_type] = fn
        return fn

    return decorator


def request_approval(
    session: Session,
    *,
    action_type: str,
    payload: dict[str, Any],
    preview_text: str,
    run_id: int | None = None,
) -> Approval:
    """Toda escrita externa nasce aqui. Auto-executa só se houver flag ligada
    para a ação — e deleção jamais auto-executa."""
    approval = Approval(
        run_id=run_id,
        action_type=action_type,
        payload_json=payload,
        preview_text=preview_text,
    )
    session.add(approval)
    session.flush()

    flag = session.get(ActionFlag, action_type)
    auto = bool(flag and flag.auto_execute) and action_type not in DELETE_ACTIONS
    if auto:
        approval.status = "approved"
        approval.decided_by = "auto-flag"
        approval.decided_at = utcnow()
        _execute(session, approval)

    session.commit()
    return approval


def approve(session: Session, approval_id: int, decided_by: str) -> Approval:
    approval = _get_pending(session, approval_id)
    approval.status = "approved"
    approval.decided_by = decided_by
    approval.decided_at = utcnow()
    _execute(session, approval)
    session.commit()
    return approval


def reject(
    session: Session, approval_id: int, decided_by: str, reason: str | None = None
) -> Approval:
    approval = _get_pending(session, approval_id)
    approval.status = "rejected"
    approval.decided_by = decided_by
    approval.decided_at = utcnow()
    approval.reject_reason = reason
    session.commit()
    return approval


def _get_pending(session: Session, approval_id: int) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise LookupError(f"approval {approval_id} não existe")
    if approval.status != "pending":
        raise ApprovalStateError(
            f"approval {approval_id} já está '{approval.status}' — decisão é única"
        )
    return approval


def _execute(session: Session, approval: Approval) -> None:
    """Executa o payload congelado e audita. Nunca relança: falha vira status."""
    executor = _EXECUTORS.get(approval.action_type)
    if executor is None:
        approval.status = "failed"
        approval.error = f"nenhum executor registrado para '{approval.action_type}'"
        return

    try:
        result = executor(dict(approval.payload_json))
    except Exception as exc:  # noqa: BLE001 — falha externa não pode derrubar o app
        approval.status = "failed"
        approval.error = str(exc)
        result = None
    else:
        approval.status = "executed"
        approval.executed_at = utcnow()

    session.add(
        AuditLog(
            run_id=approval.run_id,
            tool_name=f"approval:{approval.action_type}",
            input_json=approval.payload_json,
            output_json={"result": result, "status": approval.status, "error": approval.error},
            is_write=True,
            approval_id=approval.id,
        )
    )
