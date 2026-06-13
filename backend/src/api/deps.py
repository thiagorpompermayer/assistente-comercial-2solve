"""Dependencies do FastAPI — pontos de injeção sobrescritos nos testes."""

from __future__ import annotations

from collections.abc import Callable

from src.db.session import get_db  # noqa: F401 — reexportado como dependency padrão

MonitorRunner = Callable[[int], None]
"""Recebe o run_id pré-criado (status queued) e executa a varredura do monitor."""

EmailRunner = Callable[[int], None]
"""Recebe o run_id pré-criado (status queued) e executa a triagem da inbox."""


def get_monitor_runner() -> MonitorRunner:
    def _run(run_id: int) -> None:
        from src.agents.monitor_agent import MonitorAgent, build_overdue_demand
        from src.db.session import get_session_factory

        agent = MonitorAgent(get_session_factory())
        agent.run_demand(build_overdue_demand(), trigger="api", run_id=run_id)

    return _run


def get_email_runner() -> EmailRunner:
    def _run(run_id: int) -> None:
        from src.agents.email_agent import EmailAgent, build_triage_demand
        from src.db.session import get_session_factory

        agent = EmailAgent(get_session_factory())
        agent.run_demand(build_triage_demand(), trigger="api", run_id=run_id)

    return _run


def get_graph_client():
    from src.connectors.ms365 import GraphClient

    return GraphClient()


ProposalRunner = Callable[[int, int], None]
"""Recebe (proposal_id, run_id) e executa a geração da proposta."""


def get_proposal_runner() -> ProposalRunner:
    def _run(proposal_id: int, run_id: int) -> None:
        from src.agents.proposal_agent import ProposalAgent
        from src.db.session import get_session_factory

        agent = ProposalAgent(get_session_factory())
        agent.run_generation(proposal_id, trigger="api", run_id=run_id)

    return _run


CrmRunner = Callable[[str, int], None]
"""Recebe (demanda livre, run_id) e executa o crm_agent."""


def get_crm_runner() -> CrmRunner:
    def _run(demand: str, run_id: int) -> None:
        from src.agents.crm_agent import CrmAgent
        from src.db.session import get_session_factory

        agent = CrmAgent(get_session_factory())
        agent.run_demand(demand, trigger="api", run_id=run_id)

    return _run
