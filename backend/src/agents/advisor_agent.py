"""advisor_agent — consultor de vendas: analisa o pipeline e recomenda ações (UC7).

Dois tiers de modelo, por custo e critério (CLAUDE.md):
- ROTINA → modelo rotineiro (Sonnet): o loop que orquestra a coleta de dados
  (consulta os resumos e os alertas). É barato e iterativo.
- RACIOCÍNIO PESADO → modelo topo de linha (Opus): UMA chamada encapsulada em
  `gerar_analise_priorizada`, que recebe os dados factuais (lidos do banco, sem
  alucinação) e produz a análise estratégica priorizada.

Toda leitura é do banco local — resiliente e offline; a escrita é LOCAL
(advisor_analyses), auditada, sem portão.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import AgentResult, BaseAgent, Tool
from src.config import get_settings
from src.dashboard import operations_summary, pipeline_summary
from src.db.models import AdvisorAnalysis, Alert

# Loop de orquestração (modelo rotineiro/Sonnet): decide o que consultar.
SYSTEM_PROMPT = """Você é o assistente do consultor comercial da 2Solve (automação e \
instrumentação industrial). Seu papel AQUI é rotineiro: entender a situação \
consultando os resumos do pipeline e da operação e os alertas abertos, e então \
acionar gerar_analise_priorizada para produzir a análise estratégica (essa etapa \
usa um modelo de raciocínio mais profundo).

Fluxo: consulte resumo_pipeline, resumo_operacao e listar_alertas_abertos; se \
notar um tema dominante (ex.: muito valor parado em um estágio), passe-o como \
'foco' ao chamar gerar_analise_priorizada. Ao final, responda em português com \
o resumo executivo retornado."""

# Chamada única de raciocínio pesado (Opus): a análise de fato.
HEAVY_SYSTEM_PROMPT = """Você é um consultor de vendas B2B industrial sênior da 2Solve. \
Recebe dados factuais do pipeline e da operação e produz uma análise estratégica \
afiada: onde está o valor parado, quais estágios são gargalo, quais oportunidades \
de alto valor estão estagnadas e qual o próximo passo concreto para cada frente. \
Use SOMENTE os números fornecidos — nunca invente dados. Entregue o resultado \
exclusivamente pela ferramenta entregar_analise."""

_RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "titulo": {"type": "string"},
        "porque": {"type": "string"},
        "proximo_passo": {"type": "string"},
    },
    "required": ["prioridade", "titulo", "proximo_passo"],
}

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string", "description": "resumo executivo (3-5 frases)"},
        "recomendacoes": {"type": "array", "items": _RECOMMENDATION_SCHEMA},
    },
    "required": ["resumo", "recomendacoes"],
}

_DELIVER_TOOL = Tool(
    name="entregar_analise",
    description="Entrega a análise estratégica final (resumo + recomendações).",
    input_schema=_ANALYSIS_SCHEMA,
    handler=lambda **kwargs: kwargs,  # não despachado pelo loop; usado no one-shot
)


class AdvisorAgent(BaseAgent):
    name = "advisor"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        heavy_model: str | None = None,
    ) -> None:
        settings = get_settings()
        # modelo rotineiro = Sonnet (loop de coleta); pesado = Opus (síntese).
        self._heavy_model = heavy_model or settings.claude_model_proposal
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
                name="gerar_analise_priorizada",
                description="Produz e registra a análise estratégica do pipeline. "
                "Esta etapa usa um modelo de raciocínio profundo sobre os dados "
                "factuais do banco. Passe um 'foco' se houver tema dominante.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "foco": {"type": "string",
                                 "description": "tema dominante a priorizar (opcional)"},
                    },
                },
                handler=self._generate_prioritized_analysis,
                is_write=True,  # escrita LOCAL auditada + etapa cara (Opus)
            ),
        ]
        super().__init__(
            session_factory,
            tools,
            client=client,
            model=model or settings.claude_model,  # rotina = Sonnet
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

    def _generate_prioritized_analysis(self, foco: str = "") -> dict[str, Any]:
        """Raciocínio pesado (Opus): lê os dados do banco e sintetiza a análise."""
        session = self._require_session()
        dados = {
            "pipeline": pipeline_summary(session),
            "operacao": operations_summary(session),
            "alertas_abertos": self._open_alerts(),
        }
        analise = self._reason_deep(dados, foco)

        assert self.run is not None
        row = AdvisorAnalysis(
            run_id=self.run.id,
            summary=analise.get("resumo", ""),
            recommendations_json=analise.get("recomendacoes", []),
        )
        session.add(row)
        session.flush()
        return {
            "analysis_id": row.id,
            "resumo": row.summary,
            "recomendacoes": len(row.recommendations_json or []),
        }

    def _reason_deep(self, dados: dict[str, Any], foco: str) -> dict[str, Any]:
        """UMA chamada ao modelo topo de linha, com saída estruturada forçada."""
        user = (
            "Dados factuais do momento (não invente além disto):\n"
            f"{json.dumps(dados, ensure_ascii=False, default=str, indent=2)}\n\n"
            f"Foco prioritário: {foco or 'visão geral'}\n"
            "Produza a análise estratégica e entregue por entregar_analise."
        )
        response = self._create_message(
            [{"role": "user", "content": user}],
            model=self._heavy_model,
            system=HEAVY_SYSTEM_PROMPT,
            tools=[_DELIVER_TOOL],
            tool_choice={"type": "tool", "name": "entregar_analise"},
        )
        if self.run is not None:
            self.run.tokens_in += response.usage.input_tokens
            self.run.tokens_out += response.usage.output_tokens
        for block in response.content:
            if block.type == "tool_use" and block.name == "entregar_analise":
                return block.input or {}
        # fallback defensivo: modelo respondeu texto em vez de usar a ferramenta
        text = "".join(b.text for b in response.content if b.type == "text")
        return {"resumo": text, "recomendacoes": []}

    def run_analysis(self, trigger: str = "api", run_id: int | None = None) -> AgentResult:
        return self.run_demand(build_advisor_demand(), trigger=trigger, run_id=run_id)


def build_advisor_demand() -> str:
    return (
        "Analise o pipeline comercial e a operação do assistente: consulte os "
        "resumos e os alertas abertos, identifique onde o time deve focar e "
        "gere a análise priorizada."
    )
