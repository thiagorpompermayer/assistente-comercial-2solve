"""email_agent: triagem, rascunho e envio/exclusão sempre via portão."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.email_agent import EmailAgent, build_triage_demand
from src.db.models import Approval, EmailTriaged


class StubGraph:
    def __init__(self):
        self.reply_drafts = []
        self.forward_drafts = []

    def list_messages(self, folder="inbox", top=25):
        return [
            {
                "id": "m1",
                "subject": "Pedido de orçamento - instrumentação",
                "from": {"emailAddress": {"name": "João", "address": "joao@usinax.com"}},
                "bodyPreview": "Gostaríamos de orçar a adequação...",
                "receivedDateTime": "2026-06-12T09:00:00Z",
                "isRead": False,
            }
        ]

    def get_message(self, message_id):
        return {
            "id": message_id,
            "subject": "Pedido de orçamento - instrumentação",
            "body": {"contentType": "text", "content": "Gostaríamos de orçar a adequação"
                     " da instrumentação da planta. Podem nos visitar?"},
        }

    def create_reply_draft(self, message_id, comment, reply_all=False):
        self.reply_drafts.append((message_id, comment, reply_all))
        return {"id": f"draft-de-{message_id}"}

    def create_forward_draft(self, message_id, to, comment=""):
        self.forward_drafts.append((message_id, to, comment))
        return {"id": f"fwd-de-{message_id}"}


def make_agent(session_factory, responses, graph=None):
    return EmailAgent(
        session_factory, graph=graph or StubGraph(), client=FakeAnthropic(responses)
    )


def test_triagem_classifica_rascunha_e_enfileira_envio(session_factory):
    graph = StubGraph()
    responses = [
        FakeResponse([ToolUseBlock("t1", "listar_emails", {"quantidade": 10})], "tool_use"),
        FakeResponse(
            [
                ToolUseBlock(
                    "t2",
                    "classificar_email",
                    {
                        "message_id": "m1",
                        "classification": "lead",
                        "summary": "Lead pedindo orçamento de adequação. Responder e "
                        "agendar visita.",
                        "sender": "joao@usinax.com",
                        "subject": "Pedido de orçamento - instrumentação",
                        "received_at": "2026-06-12T09:00:00Z",
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "t3",
                    "rascunhar_resposta",
                    {"message_id": "m1",
                     "diretrizes": "Agradecer o contato, confirmar interesse e "
                     "propor visita técnica para levantamento."},
                )
            ],
            "tool_use",
        ),
        # redação da resposta (modelo de escrita cuidada, dentro do handler)
        FakeResponse(
            [TextBlock("Prezado João,\n\nObrigado pelo contato. Podemos agendar uma "
                       "visita técnica para o levantamento.\n\nAtenciosamente,\n2Solve")],
            "end_turn",
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "t4",
                    "solicitar_envio",
                    {
                        "draft_id": "draft-de-m1",
                        "para": "joao@usinax.com",
                        "assunto": "RE: Pedido de orçamento - instrumentação",
                        "resumo": "Agradece o contato e propõe visita técnica.",
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("Triagem: 1 lead, 1 rascunho aguardando aprovação.")],
                     "end_turn"),
    ]
    agent = make_agent(session_factory, responses, graph=graph)

    result = agent.run_triage(trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        triage = s.query(EmailTriaged).one()
        assert triage.classification == "lead"
        assert triage.graph_message_id == "m1"
        assert triage.draft_id == "draft-de-m1"  # rascunho vinculado à triagem
        assert triage.run_id == result.run_id

        approval = s.query(Approval).one()
        assert approval.action_type == "email_send"
        assert approval.status == "pending"  # NADA foi enviado
        assert approval.payload_json == {"draft_id": "draft-de-m1"}
        assert "joao@usinax.com" in approval.preview_text
        assert approval.run_id == result.run_id

    # o corpo veio da redação (modelo de escrita cuidada), não do loop de triagem
    assert len(graph.reply_drafts) == 1
    msg_id, corpo, reply_all = graph.reply_drafts[0]
    assert msg_id == "m1"
    assert "visita técnica" in corpo
    assert reply_all is False

    # tiering: triagem no modelo rotineiro, redação no modelo pesado
    from src.config import get_settings

    settings = get_settings()
    calls = agent._client.messages.calls
    # a chamada de redação é a única sem ferramentas (geração de texto puro)
    draft_calls = [c for c in calls if not c.get("tools")]
    assert len(draft_calls) == 1
    assert draft_calls[0]["model"] == settings.claude_model_proposal
    triage_calls = [c for c in calls if c.get("tools")]
    assert all(c["model"] == settings.claude_model for c in triage_calls)


def test_exclusao_sempre_vira_aprovacao_pendente(session_factory):
    responses = [
        FakeResponse(
            [
                ToolUseBlock(
                    "t1",
                    "solicitar_exclusao",
                    {"message_id": "spam-1", "motivo": "spam recorrente"},
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("Exclusão solicitada.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_demand("exclua o spam", trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        approval = s.query(Approval).one()
        assert approval.action_type == "email_delete"
        assert approval.status == "pending"
        assert approval.payload_json == {"message_id": "spam-1"}


def test_agente_nao_tem_ferramenta_de_envio_direto(session_factory):
    agent = make_agent(session_factory, responses=[])
    nomes = set(agent._tools_by_name)
    assert "solicitar_envio" in nomes and "solicitar_exclusao" in nomes
    assert not nomes & {"enviar_email", "send_draft", "excluir_email", "deletar_email"}


def test_demanda_de_triagem_inclui_data():
    from datetime import date

    assert "2026-06-12" in build_triage_demand(date(2026, 6, 12))
