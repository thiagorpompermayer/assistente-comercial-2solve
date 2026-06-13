"""engineering_agent — conteúdo técnico de engenharia para propostas (UC6).

Atua como engenheiro de automação e instrumentação: valida TAGs ISA-5.1,
monta listas de instrumentos, gera fluxogramas de processo (Mermaid) e
memoriais descritivos. Apoia adequação e engenharia reversa.

Toda saída é ESCRITA LOCAL (tabela engineering_artifacts) — não toca sistema
externo, então não passa pelo portão; ainda assim é auditada. Pode vincular
o artefato a uma proposta (proposal_id) para o proposal_agent reaproveitar.
"""

from __future__ import annotations

from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import BaseAgent, Tool
from src.connectors.engineering import (
    analyze_isa_tag,
    build_flowchart_mermaid,
    build_instrument_list,
)
from src.db.models import EngineeringArtifact

SYSTEM_PROMPT = """Você é o agente de engenharia da 2Solve, atuando como engenheiro \
sênior de automação e instrumentação industrial. Você produz conteúdo técnico \
para propostas: fluxogramas de processo, listas de instrumentos com TAGs \
ISA-5.1, memoriais descritivos e apoio a adequação/engenharia reversa.

Princípios:
1. Rigor ISA-5.1: valide TAGs com analisar_tag_isa antes de incluí-las em uma
   lista. TAG bem formada = primeira letra (variável medida) + letras de
   função. Ex.: FT (vazão+transmissão), PIC (pressão+indicação+controle),
   LSH (nível+chave+alto).
2. Não invente dados de processo (faixas, fluidos, pressões) que não estejam
   na demanda. Quando faltar, registre a premissa explicitamente como tal.
3. Para fluxograma, modele o processo com nós (equipamentos/instrumentos) e
   conexões (correntes de processo) coerentes com a engenharia descrita.
4. Memorial descritivo: linguagem técnica de engenharia, objetiva, com
   referência às malhas de controle e à filosofia de operação quando houver.
5. Se a demanda citar uma proposta, vincule os artefatos a ela.

Ao final, responda em português listando os artefatos que você registrou."""

INSTRUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "tag": {"type": "string"},
        "servico": {"type": "string", "description": "serviço/medição"},
        "tipo": {"type": "string"},
        "faixa": {"type": "string"},
        "sinal": {"type": "string", "description": "ex.: 4-20 mA / HART"},
        "pid": {"type": "string", "description": "referência P&ID / malha"},
    },
    "required": ["tag"],
}

NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "shape": {"type": "string", "enum": ["rect", "round", "circle", "diamond"]},
    },
    "required": ["id", "label"],
}

EDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "from": {"type": "string"},
        "to": {"type": "string"},
        "label": {"type": "string"},
    },
    "required": ["from", "to"],
}


class EngineeringAgent(BaseAgent):
    name = "engineering"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
    ) -> None:
        self._proposal_id: int | None = None
        tools = [
            Tool(
                name="analisar_tag_isa",
                description="Decompõe e valida uma TAG no padrão ISA-5.1, explicando "
                "variável medida e funções. Use antes de montar listas.",
                input_schema={
                    "type": "object",
                    "properties": {"tag": {"type": "string"}},
                    "required": ["tag"],
                },
                handler=lambda tag: analyze_isa_tag(tag).model_dump(),
            ),
            Tool(
                name="registrar_lista_instrumentos",
                description="Monta e registra uma lista de instrumentos (valida cada "
                "TAG ISA-5.1 e aponta pendências).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "instrumentos": {"type": "array", "items": INSTRUMENT_SCHEMA},
                    },
                    "required": ["titulo", "instrumentos"],
                },
                handler=self._register_instrument_list,
                is_write=True,  # escrita LOCAL auditada
            ),
            Tool(
                name="gerar_fluxograma",
                description="Gera e registra um fluxograma de processo em Mermaid a "
                "partir de nós (equipamentos/instrumentos) e conexões (correntes).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "direcao": {"type": "string", "enum": ["LR", "TB", "TD", "RL", "BT"],
                                    "default": "LR"},
                        "nos": {"type": "array", "items": NODE_SCHEMA},
                        "conexoes": {"type": "array", "items": EDGE_SCHEMA},
                    },
                    "required": ["titulo", "nos", "conexoes"],
                },
                handler=self._register_flowchart,
                is_write=True,
            ),
            Tool(
                name="registrar_memorial",
                description="Registra um memorial descritivo técnico (Markdown).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "markdown": {"type": "string"},
                    },
                    "required": ["titulo", "markdown"],
                },
                handler=self._register_memorial,
                is_write=True,
            ),
        ]
        super().__init__(session_factory, tools, client=client, model=model)

    def _save(
        self, kind: str, title: str, content_json: dict[str, Any] | None, content_text: str
    ) -> int:
        assert self.session is not None and self.run is not None
        artifact = EngineeringArtifact(
            run_id=self.run.id,
            proposal_id=self._proposal_id,
            kind=kind,
            title=title,
            content_json=content_json,
            content_text=content_text,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact.id

    def _register_instrument_list(
        self, titulo: str, instrumentos: list[dict[str, Any]]
    ) -> dict[str, Any]:
        result = build_instrument_list(instrumentos)
        artifact_id = self._save("instrument_list", titulo, result, "")
        return {"artifact_id": artifact_id, "total": result["total"],
                "pendencias": result["pendencias"]}

    def _register_flowchart(
        self,
        titulo: str,
        nos: list[dict[str, str]],
        conexoes: list[dict[str, str]],
        direcao: str = "LR",
    ) -> dict[str, Any]:
        mermaid = build_flowchart_mermaid(nos, conexoes, direction=direcao)
        artifact_id = self._save(
            "flowchart", titulo, {"nos": nos, "conexoes": conexoes}, mermaid
        )
        return {"artifact_id": artifact_id, "mermaid": mermaid}

    def _register_memorial(self, titulo: str, markdown: str) -> dict[str, Any]:
        artifact_id = self._save("memorial", titulo, None, markdown)
        return {"artifact_id": artifact_id}

    def run_demand(  # type: ignore[override]
        self, demand: str, trigger: str = "api", run_id: int | None = None,
        proposal_id: int | None = None,
    ):
        self._proposal_id = proposal_id
        return super().run_demand(demand, trigger=trigger, run_id=run_id)
