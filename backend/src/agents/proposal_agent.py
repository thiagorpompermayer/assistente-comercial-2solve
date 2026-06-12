"""proposal_agent — monta a proposta técnica-comercial PPTX padrão 2Solve (UC4).

Fontes: dados do cliente no Omie (leitura) + inputs do frontend (escopo,
itens, prazo, condições). Gera o PPTX localmente e salva no OneDrive
(escrita permitida a este agente pela tabela do CLAUDE.md — auditada).
Usa o modelo de proposta (CLAUDE_MODEL_PROPOSAL, padrão Opus).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import AgentResult, BaseAgent, Tool
from src.config import get_settings
from src.connectors.ms365 import GraphClient
from src.connectors.omie import OmieClient
from src.connectors.pptx_2solve import (
    ProposalContent,
    build_proposal_pptx,
    proposal_filename,
)
from src.db.models import Proposal

SYSTEM_PROMPT = """Você monta propostas técnico-comerciais da 2Solve (automação e \
instrumentação industrial) atuando como consultor de vendas B2B e engenheiro \
de automação ao mesmo tempo.

Processo:
1. Se houver código de cliente Omie, consulte os dados cadastrais com
   consultar_cliente_omie e use a razão social/nome fantasia corretos.
2. Redija o conteúdo da proposta a partir dos inputs recebidos:
   - titulo: curto e orientado ao valor para o cliente (não repita "proposta").
   - subtitulo: 1 frase com o benefício central da solução.
   - escopo: bullets objetivos (verbo no infinitivo), linguagem de engenharia
     correta (TAGs, malhas, instrumentos quando aplicável).
   - observacoes: notas comerciais relevantes (frete, impostos, exclusões).
3. REGRA ABSOLUTA: use os itens, quantidades e valores EXATAMENTE como
   informados nos inputs — nunca invente, altere ou estime preço. Item sem
   valor informado fica com valor_unitario nulo (sai como "sob consulta").
4. Chame gerar_pptx com o conteúdo completo.
5. Chame salvar_onedrive para publicar o arquivo na pasta de propostas.

Ao final, responda com um resumo do que foi gerado (título, nº de itens,
onde foi salvo)."""


class ProposalAgent(BaseAgent):
    name = "proposal"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        omie: OmieClient | None = None,
        graph: GraphClient | None = None,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        output_dir: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._omie = omie or OmieClient()
        self._graph = graph or GraphClient()
        self._output_dir = output_dir or Path(settings.proposals_output_dir)
        self._proposal_id: int | None = None
        tools = [
            Tool(
                name="consultar_cliente_omie",
                description="Consulta os dados cadastrais de um cliente no Omie.",
                input_schema={
                    "type": "object",
                    "properties": {"codigo_cliente_omie": {"type": "integer"}},
                    "required": ["codigo_cliente_omie"],
                },
                handler=lambda codigo_cliente_omie: self._omie.get_client(
                    codigo_cliente_omie
                ),
            ),
            Tool(
                name="gerar_pptx",
                description="Gera o arquivo PPTX da proposta no padrão visual 2Solve. "
                "Itens e valores devem ser exatamente os informados na demanda.",
                input_schema=ProposalContent.model_json_schema(),
                handler=self._generate_pptx,
                is_write=True,  # escrita LOCAL auditada
            ),
            Tool(
                name="salvar_onedrive",
                description="Publica o PPTX gerado na pasta de propostas do OneDrive "
                "comercial e retorna o link.",
                input_schema={"type": "object", "properties": {}},
                handler=self._upload_onedrive,
                is_write=True,  # escrita externa permitida a este agente; auditada
            ),
        ]
        super().__init__(
            session_factory,
            tools,
            client=client,
            model=model or settings.claude_model_proposal,
        )

    def _get_proposal(self) -> Proposal:
        assert self.session is not None and self._proposal_id is not None
        proposal = self.session.get(Proposal, self._proposal_id)
        if proposal is None:
            raise LookupError(f"proposta {self._proposal_id} não existe")
        return proposal

    def _generate_pptx(self, **conteudo: Any) -> dict[str, Any]:
        content = ProposalContent(**conteudo)
        proposal = self._get_proposal()
        path = self._output_dir / proposal_filename(content)
        build_proposal_pptx(content, path)
        proposal.pptx_path = str(path)
        proposal.status = "generated"
        self.session.flush()  # type: ignore[union-attr]
        return {"pptx_path": str(path), "slides": "capa, escopo, investimento, "
                "condições, contato"}

    def _upload_onedrive(self) -> dict[str, Any]:
        proposal = self._get_proposal()
        if not proposal.pptx_path:
            raise RuntimeError("gere o PPTX com gerar_pptx antes de salvar no OneDrive")
        path = Path(proposal.pptx_path)
        settings = get_settings()
        remote_path = f"{settings.onedrive_proposals_folder}/{path.name}"
        item = self._graph.upload_file(remote_path, path.read_bytes())
        proposal.onedrive_url = item.get("webUrl")
        self.session.flush()  # type: ignore[union-attr]
        return {"onedrive_url": proposal.onedrive_url, "remote_path": remote_path}

    def run_generation(
        self, proposal_id: int, trigger: str = "api", run_id: int | None = None
    ) -> AgentResult:
        self._proposal_id = proposal_id
        with self._session_factory() as session:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None:
                raise LookupError(f"proposta {proposal_id} não existe")
            demand = build_proposal_demand(proposal)

        result = self.run_demand(demand, trigger=trigger, run_id=run_id)

        if result.status == "error":
            with self._session_factory() as session:
                proposal = session.get(Proposal, proposal_id)
                if proposal is not None and proposal.status != "generated":
                    proposal.status = "error"
                    session.commit()
        return result


def build_proposal_demand(proposal: Proposal) -> str:
    return (
        "Monte a proposta técnico-comercial a partir destes inputs do time "
        f"comercial (proposta interna #{proposal.id}):\n\n"
        f"{json.dumps(proposal.input_json, ensure_ascii=False, indent=2)}\n\n"
        "Siga o processo do seu papel: consultar o cliente no Omie (se houver "
        "código), redigir o conteúdo, gerar o PPTX e salvar no OneDrive."
    )
