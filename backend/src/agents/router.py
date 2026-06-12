"""Orquestrador: recebe demanda (API, scheduler ou outro agente) e escolhe o agente.

Registro explícito em código próprio — sem n8n, sem SDK de agente.
Os demais agentes entram aqui nas suas etapas (email, crm, proposal...).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import AgentResult, BaseAgent
from src.agents.email_agent import EmailAgent
from src.agents.monitor_agent import MonitorAgent
from src.db.session import get_session_factory


class UnknownAgentError(LookupError):
    pass


AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "monitor": MonitorAgent,
    "email": EmailAgent,
}


def dispatch(
    agent_name: str,
    demand: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    trigger: str = "api",
    run_id: int | None = None,
    **agent_kwargs: object,
) -> AgentResult:
    agent_cls = AGENT_REGISTRY.get(agent_name)
    if agent_cls is None:
        raise UnknownAgentError(
            f"agente desconhecido: '{agent_name}' (disponíveis: {sorted(AGENT_REGISTRY)})"
        )
    agent = agent_cls(session_factory or get_session_factory(), **agent_kwargs)  # type: ignore[arg-type]
    return agent.run_demand(demand, trigger=trigger, run_id=run_id)
