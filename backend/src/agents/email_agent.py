"""email_agent — triagem da inbox, classificação e rascunhos (UC2/UC3).

Permissões (CLAUDE.md, tabela de agentes):
- Ler e rascunhar: direto no Graph (rascunho fica em Drafts, nada sai).
- Enviar/encaminhar: a ferramenta só ENFILEIRA em `approvals` (email_send).
- Excluir: idem (email_delete) — e deleção nunca auto-executa.

Dois tiers de modelo, por custo e critério (CLAUDE.md):
- ROTINA → modelo rotineiro (Sonnet): o loop de triagem — listar, ler,
  classificar. Alto volume, barato.
- ESCRITA AO CLIENTE → modelo topo de linha (Opus): a redação da resposta que
  de fato vai para o cliente é feita numa chamada encapsulada em
  `rascunhar_resposta`, a partir das diretrizes. O encaminhamento interno
  segue rotineiro (comentário curto, mecânico).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import BaseAgent, Tool
from src.approvals import request_approval
from src.config import get_settings
from src.connectors.ms365 import GraphClient
from src.db.models import EmailTriaged

SYSTEM_PROMPT = """Você é o agente de email do time comercial da 2Solve (automação e \
instrumentação industrial). Você faz a triagem da caixa comercial como um \
consultor de vendas B2B experiente.

Classificações possíveis:
- lead: contato novo com potencial de negócio (pedido de orçamento, indicação).
- cliente_ativo: cliente ou oportunidade em andamento.
- fornecedor: fornecedor, parceiro ou prestador.
- interno: assunto interno da 2Solve.
- irrelevante: spam, marketing, sem ação necessária.

Fluxo de trabalho:
1. Liste os emails recentes e leia na íntegra os que parecem relevantes.
2. Classifique TODOS os listados com classificar_email (resumo de 1-2 frases
   dizendo o que o remetente quer e a ação recomendada).
3. Para lead e cliente_ativo que pedem resposta, chame rascunhar_resposta
   passando as DIRETRIZES do que a resposta deve abordar (pontos, dados a
   confirmar, próximo passo) — NÃO escreva você o texto final: a redação é
   feita por um modelo de escrita cuidada. Não inclua promessas de prazo ou
   preço que não estejam nos dados.
4. Se um email deve ir para outra pessoa do time, use rascunhar_encaminhamento.
5. Use solicitar_envio apenas quando o rascunho estiver completo e
   autossuficiente — um humano vai revisar e aprovar antes de sair.
6. NUNCA invente informações. Se faltar contexto para responder, classifique
   e diga no resumo o que falta.

Você não tem ferramenta de envio direto nem de exclusão direta: envio e
exclusão viram pedidos de aprovação humana, sempre.

Ao final, responda com um resumo em português da triagem feita."""

# Redação da resposta ao cliente (modelo de escrita cuidada / Opus).
DRAFT_SYSTEM_PROMPT = """Você redige respostas comerciais da 2Solve (automação e \
instrumentação industrial) para clientes e leads. Escreva em português \
brasileiro, tom profissional e cordial, direto ao ponto, na primeira pessoa do \
plural (em nome da 2Solve). Use SOMENTE as informações das diretrizes e do \
email recebido — nunca invente prazos, preços ou compromissos. Estruture com \
saudação, corpo objetivo e fechamento com próximo passo claro. Responda apenas \
com o corpo do email, sem assunto e sem comentários."""


class EmailAgent(BaseAgent):
    name = "email"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        graph: GraphClient | None = None,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        heavy_model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._graph = graph or GraphClient()
        # rotina = Sonnet (loop de triagem); escrita ao cliente = Opus.
        self._heavy_model = heavy_model or settings.claude_model_proposal
        tools = [
            Tool(
                name="listar_emails",
                description="Lista os emails mais recentes da caixa comercial.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "quantidade": {"type": "integer", "minimum": 1, "maximum": 50,
                                       "default": 25},
                    },
                },
                handler=self._list_emails,
            ),
            Tool(
                name="ler_email",
                description="Lê um email na íntegra (corpo completo e destinatários).",
                input_schema={
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
                handler=self._read_email,
            ),
            Tool(
                name="classificar_email",
                description="Registra a classificação de um email triado.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "classification": {
                            "type": "string",
                            "enum": ["lead", "cliente_ativo", "fornecedor", "interno",
                                     "irrelevante"],
                        },
                        "summary": {"type": "string",
                                    "description": "1-2 frases: o que o remetente quer e a "
                                    "ação recomendada"},
                        "sender": {"type": "string"},
                        "subject": {"type": "string"},
                        "received_at": {"type": "string"},
                    },
                    "required": ["message_id", "classification", "summary"],
                },
                handler=self._classify,
                is_write=True,  # escrita LOCAL auditada
            ),
            Tool(
                name="rascunhar_resposta",
                description="Redige (com modelo de escrita cuidada) e cria um RASCUNHO "
                "de resposta no Outlook a partir das DIRETRIZES. Não envia nada.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "diretrizes": {"type": "string",
                                       "description": "o que a resposta deve abordar: "
                                       "pontos, dados a confirmar, próximo passo"},
                        "instrucoes_tom": {"type": "string",
                                           "description": "ajuste de tom opcional"},
                        "responder_todos": {"type": "boolean", "default": False},
                    },
                    "required": ["message_id", "diretrizes"],
                },
                handler=self._draft_reply,
                is_write=True,  # escreve na pasta Drafts — permitido, auditado
            ),
            Tool(
                name="rascunhar_encaminhamento",
                description="Cria um RASCUNHO de encaminhamento no Outlook (não envia nada).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "para": {"type": "array", "items": {"type": "string"},
                                 "description": "endereços de destino"},
                        "comentario": {"type": "string", "default": ""},
                    },
                    "required": ["message_id", "para"],
                },
                handler=self._draft_forward,
                is_write=True,
            ),
            Tool(
                name="solicitar_envio",
                description="Enfileira o envio de um rascunho para APROVAÇÃO HUMANA. "
                "Nada é enviado até alguém aprovar.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "para": {"type": "string", "description": "destinatário(s) legível"},
                        "assunto": {"type": "string"},
                        "resumo": {"type": "string",
                                   "description": "resumo do conteúdo para o aprovador"},
                    },
                    "required": ["draft_id", "para", "assunto", "resumo"],
                },
                handler=self._request_send,
                is_write=True,
            ),
            Tool(
                name="solicitar_exclusao",
                description="Enfileira a exclusão de um email para APROVAÇÃO HUMANA "
                "(move para Itens Excluídos se aprovado). Nunca executa direto.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"},
                        "motivo": {"type": "string"},
                    },
                    "required": ["message_id", "motivo"],
                },
                handler=self._request_delete,
                is_write=True,
            ),
        ]
        super().__init__(session_factory, tools, client=client, model=model)

    # ----- leituras -----

    def _list_emails(self, quantidade: int = 25) -> list[dict[str, Any]]:
        messages = self._graph.list_messages(top=quantidade)
        return [
            {
                "message_id": m.get("id"),
                "de": (m.get("from", {}).get("emailAddress", {}) or {}),
                "assunto": m.get("subject"),
                "previa": m.get("bodyPreview"),
                "recebido_em": m.get("receivedDateTime"),
                "lido": m.get("isRead"),
            }
            for m in messages
        ]

    def _read_email(self, message_id: str) -> dict[str, Any]:
        return self._graph.get_message(message_id)

    # ----- escritas locais / rascunhos -----

    def _classify(
        self,
        message_id: str,
        classification: str,
        summary: str,
        sender: str | None = None,
        subject: str | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        row = EmailTriaged(
            run_id=self.run.id,
            graph_message_id=message_id,
            classification=classification,
            summary=summary,
            sender=sender,
            subject=subject,
            received_at=received_at,
        )
        self.session.add(row)
        self.session.flush()
        return {"triage_id": row.id}

    def _link_draft(self, message_id: str, draft_id: str) -> None:
        assert self.session is not None
        row = (
            self.session.query(EmailTriaged)
            .filter_by(graph_message_id=message_id)
            .order_by(EmailTriaged.id.desc())
            .first()
        )
        if row is not None:
            row.draft_id = draft_id

    def _draft_reply(
        self,
        message_id: str,
        diretrizes: str,
        instrucoes_tom: str = "",
        responder_todos: bool = False,
    ) -> dict[str, Any]:
        original = self._graph.get_message(message_id)
        corpo = self._compose_reply(original, diretrizes, instrucoes_tom)
        draft = self._graph.create_reply_draft(message_id, corpo, reply_all=responder_todos)
        draft_id = draft.get("id", "")
        self._link_draft(message_id, draft_id)
        return {"draft_id": draft_id, "corpo": corpo}

    def _compose_reply(
        self, original: dict[str, Any], diretrizes: str, instrucoes_tom: str
    ) -> str:
        """Redação da resposta ao cliente — UMA chamada ao modelo topo de linha."""
        corpo_original = (original.get("body") or {}).get("content", "")
        user = (
            f"Email recebido:\nAssunto: {original.get('subject', '')}\n"
            f"{corpo_original}\n\n"
            f"Diretrizes da resposta: {diretrizes}\n"
            f"Tom: {instrucoes_tom or 'profissional e cordial'}\n"
            "Escreva o corpo da resposta."
        )
        response = self._create_message(
            [{"role": "user", "content": user}],
            model=self._heavy_model,
            system=DRAFT_SYSTEM_PROMPT,
            tools=[],  # geração de texto puro, sem ferramentas
        )
        if self.run is not None:
            self.run.tokens_in += response.usage.input_tokens
            self.run.tokens_out += response.usage.output_tokens
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _draft_forward(
        self, message_id: str, para: list[str], comentario: str = ""
    ) -> dict[str, Any]:
        draft = self._graph.create_forward_draft(message_id, to=para, comment=comentario)
        draft_id = draft.get("id", "")
        self._link_draft(message_id, draft_id)
        return {"draft_id": draft_id}

    # ----- escritas externas: SÓ enfileiram no portão -----

    def _request_send(
        self, draft_id: str, para: str, assunto: str, resumo: str
    ) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        approval = request_approval(
            self.session,
            action_type="email_send",
            payload={"draft_id": draft_id},
            preview_text=f"Enviar email para {para}\nAssunto: {assunto}\n\n{resumo}",
            run_id=self.run.id,
        )
        return {"approval_id": approval.id, "status": approval.status}

    def _request_delete(self, message_id: str, motivo: str) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        approval = request_approval(
            self.session,
            action_type="email_delete",
            payload={"message_id": message_id},
            preview_text=f"Excluir email {message_id} (mover para Itens Excluídos)\n"
            f"Motivo: {motivo}",
            run_id=self.run.id,
        )
        return {"approval_id": approval.id, "status": approval.status}

    def run_triage(self, trigger: str = "scheduler", run_id: int | None = None):
        return self.run_demand(build_triage_demand(), trigger=trigger, run_id=run_id)


def build_triage_demand(today: date | None = None) -> str:
    today = today or date.today()
    return (
        f"Hoje é {today.isoformat()}. Faça a triagem dos emails mais recentes da "
        "caixa comercial: liste, leia os relevantes, classifique todos e rascunhe "
        "resposta para os que merecem. Solicite aprovação de envio apenas para "
        "rascunhos completos."
    )
