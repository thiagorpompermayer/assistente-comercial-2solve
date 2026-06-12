"""monitor_agent — vigia atrasos e follow-ups pendentes (UC1, só leitura externa).

Leituras: Omie (oportunidades, tarefas) e calendário M365.
Única escrita: alertas no banco LOCAL (tabela alerts) — não passa pelo portão
de aprovação porque não toca sistema externo; ainda assim é auditada.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import BaseAgent, Tool
from src.connectors.ms365 import GraphClient
from src.connectors.omie import OmieClient
from src.db.models import Alert

SYSTEM_PROMPT = """Você é o agente monitor do time comercial da 2Solve (automação e \
instrumentação industrial). Sua função é varrer o CRM Omie e o calendário e \
identificar atrasos reais: tarefas vencidas, follow-ups pendentes e \
oportunidades paradas há tempo demais.

Critérios:
- Tarefa com data prevista anterior a hoje e não concluída → task_overdue.
- Oportunidade sem movimentação/contato há 7+ dias em estágio ativo → followup_overdue.
- Proposta enviada sem resposta há 7+ dias → proposal_stale.

Seja conservador: alerte apenas o que está de fato vencido pelos dados — não \
invente datas nem registros. Para cada atraso real, chame criar_alerta com \
título curto e detalhe acionável (cliente, valor se houver, dias de atraso, \
próximo passo sugerido). Severidade: high para oportunidade de valor alto ou \
14+ dias; medium padrão; low para itens menores.

Ao final, responda com um resumo em português do que encontrou."""

PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pagina": {"type": "integer", "minimum": 1, "default": 1},
    },
}


class MonitorAgent(BaseAgent):
    name = "monitor"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        omie: OmieClient | None = None,
        graph: GraphClient | None = None,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
    ) -> None:
        self._omie = omie or OmieClient()
        self._graph = graph or GraphClient()
        tools = [
            Tool(
                name="omie_listar_oportunidades",
                description="Lista oportunidades do CRM Omie (paginado).",
                input_schema=PAGE_SCHEMA,
                handler=lambda pagina=1: self._omie.list_opportunities(page=pagina),
            ),
            Tool(
                name="omie_listar_tarefas",
                description="Lista tarefas/atividades do CRM Omie (paginado).",
                input_schema=PAGE_SCHEMA,
                handler=lambda pagina=1: self._omie.list_tasks(page=pagina),
            ),
            Tool(
                name="calendario_eventos",
                description="Lista eventos do calendário comercial num intervalo de dias "
                "relativo a hoje (ex.: dias_atras=7, dias_frente=7).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "dias_atras": {"type": "integer", "minimum": 0, "default": 7},
                        "dias_frente": {"type": "integer", "minimum": 0, "default": 7},
                    },
                },
                handler=self._calendar_events,
            ),
            Tool(
                name="criar_alerta",
                description="Registra um alerta de atraso para o time comercial. "
                "Use somente para atrasos reais confirmados pelos dados.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["followup_overdue", "proposal_stale", "task_overdue"],
                        },
                        "title": {"type": "string"},
                        "detail": {"type": "string"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "entity_ref": {
                            "type": "string",
                            "description": "id do registro no Omie, se houver",
                        },
                    },
                    "required": ["kind", "title", "detail"],
                },
                handler=self._create_alert,
                is_write=True,  # escrita LOCAL (auditada); não é escrita externa
            ),
        ]
        super().__init__(session_factory, tools, client=client, model=model)

    def _calendar_events(self, dias_atras: int = 7, dias_frente: int = 7) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=dias_atras)).isoformat()
        end = (now + timedelta(days=dias_frente)).isoformat()
        return self._graph.list_calendar_events(start, end)

    def _create_alert(
        self,
        kind: str,
        title: str,
        detail: str,
        severity: str = "medium",
        entity_ref: str | None = None,
    ) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        alert = Alert(
            run_id=self.run.id,
            kind=kind,
            title=title,
            detail=detail,
            severity=severity,
            entity_ref=entity_ref,
        )
        self.session.add(alert)
        self.session.flush()
        return {"alert_id": alert.id}

    def run_overdue_scan(self, trigger: str = "scheduler", run_id: int | None = None):
        return self.run_demand(build_overdue_demand(), trigger=trigger, run_id=run_id)


def build_overdue_demand(today: date | None = None) -> str:
    today = today or date.today()
    return (
        f"Hoje é {today.isoformat()}. Varra as oportunidades e tarefas do Omie e os "
        "eventos recentes do calendário; identifique atrasos conforme seus critérios "
        "e registre os alertas necessários."
    )
