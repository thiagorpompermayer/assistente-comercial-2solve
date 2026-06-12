"""Executores das ações que passaram pelo portão de aprovação.

Importar este módulo registra os executores (feito em src/main.py).
Só código daqui pode efetivar escrita externa — e só com o payload
congelado que o humano aprovou (ou flag explícita; deleção nunca).
"""

from __future__ import annotations

from typing import Any

from src.approvals import register_executor
from src.connectors.ms365 import GraphClient

_graph: GraphClient | None = None


def _get_graph() -> GraphClient:
    global _graph
    if _graph is None:
        _graph = GraphClient()
    return _graph


def set_graph_client(client: GraphClient | None) -> None:
    """Injeção para testes."""
    global _graph
    _graph = client


@register_executor("email_send")
def execute_email_send(payload: dict[str, Any]) -> dict[str, Any]:
    _get_graph().send_draft(payload["draft_id"])
    return {"sent": True, "draft_id": payload["draft_id"]}


@register_executor("email_delete")
def execute_email_delete(payload: dict[str, Any]) -> dict[str, Any]:
    moved = _get_graph().move_to_deleted(payload["message_id"])
    return {
        "moved_to": "deleteditems",  # exclusão reversível, nunca hard delete
        "message_id": payload["message_id"],
        "new_id": (moved or {}).get("id"),
    }
