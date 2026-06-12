"""Executores do portão: efetivam só o payload aprovado, via Graph."""

import pytest

from src import approvals, executors
from src.db.models import ActionFlag


class StubGraph:
    def __init__(self):
        self.sent = []
        self.moved = []

    def send_draft(self, draft_id):
        self.sent.append(draft_id)

    def move_to_deleted(self, message_id):
        self.moved.append(message_id)
        return {"id": f"{message_id}-movido"}


@pytest.fixture()
def graph():
    stub = StubGraph()
    executors.set_graph_client(stub)
    yield stub
    executors.set_graph_client(None)


def test_envio_aprovado_envia_o_draft_congelado(session, graph):
    approval = approvals.request_approval(
        session,
        action_type="email_send",
        payload={"draft_id": "draft-7"},
        preview_text="Enviar email",
    )
    assert approval.status == "pending"

    result = approvals.approve(session, approval.id, decided_by="thiago")

    assert result.status == "executed"
    assert graph.sent == ["draft-7"]


def test_exclusao_nunca_auto_executa_e_so_move_apos_aprovacao(session, graph):
    session.add(ActionFlag(action_type="email_delete", auto_execute=True))
    session.commit()

    approval = approvals.request_approval(
        session,
        action_type="email_delete",
        payload={"message_id": "m-99"},
        preview_text="Excluir email m-99",
    )
    assert approval.status == "pending"  # flag ignorada (regra dura 1)
    assert graph.moved == []

    result = approvals.approve(session, approval.id, decided_by="ana")

    assert result.status == "executed"
    assert graph.moved == ["m-99"]  # move para Itens Excluídos, não hard delete
