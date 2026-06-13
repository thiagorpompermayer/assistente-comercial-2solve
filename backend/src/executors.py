"""Executores das ações que passaram pelo portão de aprovação.

Importar este módulo registra os executores (feito em src/main.py).
Só código daqui pode efetivar escrita externa — e só com o payload
congelado que o humano aprovou (ou flag explícita; deleção nunca).
"""

from __future__ import annotations

from typing import Any

from src.approvals import register_executor
from src.connectors.ms365 import GraphClient
from src.connectors.omie import OmieClient

_graph: GraphClient | None = None
_omie: OmieClient | None = None


def _get_graph() -> GraphClient:
    global _graph
    if _graph is None:
        _graph = GraphClient()
    return _graph


def set_graph_client(client: GraphClient | None) -> None:
    """Injeção para testes."""
    global _graph
    _graph = client


def _get_omie() -> OmieClient:
    global _omie
    if _omie is None:
        _omie = OmieClient()
    return _omie


def set_omie_client(client: OmieClient | None) -> None:
    """Injeção para testes."""
    global _omie
    _omie = client


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


# ----- Omie (Etapa 5) — escrita no CRM, sempre via aprovação -----
#
# payload congelado:
#   omie_create = {"entity": "client"|"opportunity", "data": {...}}
#   omie_update = {"entity": "client"|"opportunity", "data": {...}}  (data inclui o id)

_OMIE_CREATE = {
    "client": lambda data: _get_omie().create_client(data),
    "opportunity": lambda data: _get_omie().create_opportunity(data),
}
_OMIE_UPDATE = {
    "client": lambda data: _get_omie().update_client(data),
    "opportunity": lambda data: _get_omie().update_opportunity(data),
}


def _omie_entity(payload: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    entity = payload.get("entity")
    fn = table.get(entity)
    if fn is None:
        raise ValueError(f"entidade Omie não suportada: {entity!r}")
    result = fn(payload["data"])
    return {"entity": entity, "omie_result": result}


@register_executor("omie_create")
def execute_omie_create(payload: dict[str, Any]) -> dict[str, Any]:
    return _omie_entity(payload, _OMIE_CREATE)


@register_executor("omie_update")
def execute_omie_update(payload: dict[str, Any]) -> dict[str, Any]:
    return _omie_entity(payload, _OMIE_UPDATE)
