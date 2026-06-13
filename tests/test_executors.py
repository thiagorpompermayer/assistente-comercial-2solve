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


class StubOmie:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_client(self, data):
        self.created.append(("client", data))
        return {"codigo_cliente_omie": 999}

    def create_opportunity(self, data):
        self.created.append(("opportunity", data))
        return {"nCodOp": 555}

    def update_client(self, data):
        self.updated.append(("client", data))
        return {"codigo_cliente_omie": data["codigo_cliente_omie"]}

    def update_opportunity(self, data):
        self.updated.append(("opportunity", data))
        return {"nCodOp": data["identificacao"]["nCodOp"]}


@pytest.fixture()
def omie():
    stub = StubOmie()
    executors.set_omie_client(stub)
    yield stub
    executors.set_omie_client(None)


def test_cadastro_cliente_aprovado_grava_payload_congelado(session, omie):
    data = {"codigo_cliente_integracao": "2S-00", "razao_social": "USINA X", "cnpj_cpf": "00"}
    approval = approvals.request_approval(
        session,
        action_type="omie_create",
        payload={"entity": "client", "data": data},
        preview_text="Cadastrar cliente no Omie",
    )
    assert approval.status == "pending"
    assert omie.created == []

    result = approvals.approve(session, approval.id, decided_by="thiago")

    assert result.status == "executed"
    assert omie.created == [("client", data)]  # exatamente o payload congelado


def test_omie_create_oportunidade_dispatch_por_entidade(session, omie):
    data = {"identificacao": {"cDesOp": "Nova op", "nCodClien": 999}}
    approval = approvals.request_approval(
        session,
        action_type="omie_create",
        payload={"entity": "opportunity", "data": data},
        preview_text="Cadastrar oportunidade",
    )
    approvals.approve(session, approval.id, decided_by="thiago")
    assert omie.created == [("opportunity", data)]


def test_omie_flag_auto_executa_create_mas_nao_delete(session, omie):
    # omie_create NÃO é deleção → pode auto-executar via flag (regra dura 2)
    session.add(ActionFlag(action_type="omie_create", auto_execute=True))
    session.commit()
    approval = approvals.request_approval(
        session,
        action_type="omie_create",
        payload={"entity": "client", "data": {"razao_social": "Y", "cnpj_cpf": "1"}},
        preview_text="Cadastrar cliente",
    )
    assert approval.status == "executed"
    assert approval.decided_by == "auto-flag"
    assert len(omie.created) == 1


def test_entidade_omie_invalida_marca_failed(session, omie):
    approval = approvals.request_approval(
        session,
        action_type="omie_update",
        payload={"entity": "fornecedor", "data": {}},
        preview_text="x",
    )
    result = approvals.approve(session, approval.id, decided_by="thiago")
    assert result.status == "failed"
    assert "não suportada" in result.error
