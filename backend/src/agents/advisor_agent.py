"""advisor_agent — consultor de vendas: analisa o pipeline e recomenda ações (UC7).

Lê o banco local (pipeline_cache, alertas, propostas, aprovações) e produz uma
análise com prioridades e próximos passos. Usa o modelo de raciocínio pesado
(CLAUDE_MODEL_PROPOSAL, padrão Opus). Toda leitura é do banco — resiliente e
offline; a escrita é LOCAL (advisor_analyses), auditada, sem portão.
"""

from __future__ import annotations

from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import AgentResult, BaseAgent, Tool
from src.config import get_settings
from src.dashboard import operations_summary, pipeline_summary
from src.db.models import AdvisorAnalysis, Alert

SYSTEM_PROMPT = """Você é o consultor de vendas sênior do time comercial da 2Solve \
(automação e instrumentação industrial). Sua função é analisar o pipeline e a \
operação e recomendar onde o time deve focar.

Processo:
1. Consulte resumo_pipeline (estágios, valor, ticket médio) e resumo_operacao
   (emails triados, fila de aprovações, propostas, alertas).
2. Consulte os alertas abertos para entender o que já está em atraso.
3. Analise como consultor B2B industrial: onde está o valor parado, quais
   estágios acumulam, quais oportunidades de alto valor estão estagnadas, qual
   o gargalo operacional (ex.: fila de aprovação crescendo).
4. Registre a análise com registrar_analise: um resumo executivo (3-5 frases) e
   uma lista priorizada de recomendações ACIONÁVEIS (cada uma com o porquê e o
   próximo passo concreto). Não invente números — use só os dados consultados.

Ao final, responda em português com o resumo executivo."""


class AdvisorAgent(BaseAgent):
    name = "advisor"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        tools = [
            Tool(
                name="resumo_pipeline",
                description="Resumo do pipeline comercial por estágio (valor, "
                "quantidade, ticket médio) a partir do cache local.",
                input_schema={"type": "object", "properties": {}},
                handler=lambda: pipeline_summary(self._require_session()),
            ),
            Tool(
                name="resumo_operacao",
                description="Métricas operacionais do assistente (emails triados, "
                "fila de aprovações, propostas, alertas).",
                input_schema={
                    "type": "object",
                    "properties": {"dias": {"type": "integer", "minimum": 1, "default": 30}},
                },
                handler=lambda dias=30: operations_summary(self._require_session(), days=dias),
            ),
            Tool(
                name="listar_alertas_abertos",
                description="Lista os alertas de atraso/follow-up em aberto.",
                input_schema={"type": "object", "properties": {}},
                handler=self._open_alerts,
            ),
            Tool(
                name="registrar_analise",
                description="Registra a análise do pipeline: resumo executivo + lista "
                "priorizada de recomendações acionáveis.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "resumo": {"type": "string"},
                        "recomendacoes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "prioridade": {"type": "string",
                                                   "enum": ["alta", "media", "baixa"]},
                                    "titulo": {"type": "string"},
                                    "porque": {"type": "string"},
                                    "proximo_passo": {"type": "string"},
                                },
                                "required": ["prioridade", "titulo", "proximo_passo"],
                            },
                        },
                    },
                    "required": ["resumo", "recomendacoes"],
                },
                handler=self._save_analysis,
                is_write=True,  # escrita LOCAL auditada
            ),
        ]
        super().__init__(
            session_factory,
            tools,
            client=client,
            model=model or settings.claude_model_proposal,
        )

    def _require_session(self) -> Session:
        assert self.session is not None
        return self.session

    def _open_alerts(self) -> list[dict[str, Any]]:
        session = self._require_session()
        alerts = session.scalars(
            select(Alert).where(Alert.status == "open").order_by(Alert.created_at.desc())
        )
        return [
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "detail": a.detail,
                "severity": a.severity,
                "entity_ref": a.entity_ref,
            }
            for a in alerts
        ]

    def _save_analysis(
        self, resumo: str, recomendacoes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        analysis = AdvisorAnalysis(
            run_id=self.run.id,
            summary=resumo,
            recommendations_json=recomendacoes,
        )
        self.session.add(analysis)
        self.session.flush()
        return {"analysis_id": analysis.id, "recomendacoes": len(recomendacoes)}

    def run_analysis(self, trigger: str = "api", run_id: int | None = None) -> AgentResult:
        return self.run_demand(build_advisor_demand(), trigger=trigger, run_id=run_id)


def build_advisor_demand() -> str:
    return (
        "Analise o pipeline comercial e a operação do assistente: consulte os "
        "resumos e os alertas abertos, identifique onde o time deve focar e "
        "registre a análise com recomendações priorizadas."
    )
