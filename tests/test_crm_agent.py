"""crm_agent: consulta Omie e enfileira escrita sempre via portão (nunca direto)."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.crm_agent import CrmAgent
from src.db.models import Approval, AuditLog


class StubOmie:
    def __init__(self, existing=None):
        self.existing = existing or {"total_de_registros": 0, "clientes_cadastro": []}
        self.write_called = False

    def find_client_by_document(self, cnpj_cpf):
        return self.existing

    def list_clients(self, page=1):
        return {"total_de_registros": 0, "clientes_cadastro": []}

    # se o agente tentar escrever direto, falharia — mas ele não tem como:
    def create_client(self, data):  # pragma: no cover
        self.write_called = True
        return {"codigo_cliente_omie": 1}


def make_agent(session_factory, responses, omie=None):
    return CrmAgent(
        session_factory, omie=omie or StubOmie(), client=FakeAnthropic(responses)
    )


def test_cadastro_de_cliente_busca_duplicidade_e_enfileira(session_factory):
    omie = StubOmie()
    responses = [
        FakeResponse(
            [ToolUseBlock("t1", "buscar_cliente_por_cnpj",
                          {"cnpj_cpf": "10.821.258/0001-02"})],
            "tool_use",
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "t2",
                    "solicitar_cadastro_cliente",
                    {
                        "razao_social": "USINA X S.A.",
                        "cnpj_cpf": "10.821.258/0001-02",
                        "email": "compras@usinax.com",
                        "telefone": "(27) 3026-3806",
                        "cidade": "Vitória",
                        "estado": "ES",
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("Cliente não existia; cadastro na fila de aprovação.")],
                     "end_turn"),
    ]
    agent = make_agent(session_factory, responses, omie=omie)

    result = agent.run_demand("Cadastre a USINA X (CNPJ 10.821.258/0001-02)", trigger="api")

    assert result.status == "done"
    assert omie.write_called is False  # NADA foi escrito direto no Omie
    with session_factory() as s:
        approval = s.query(Approval).one()
        assert approval.action_type == "omie_create"
        assert approval.status == "pending"
        assert approval.payload_json["entity"] == "client"
        data = approval.payload_json["data"]
        assert data["razao_social"] == "USINA X S.A."
        assert data["codigo_cliente_integracao"] == "2S-10821258000102"
        assert data["telefone1_ddd"] == "27"
        assert "USINA X" in approval.preview_text

        nomes = [a.tool_name for a in s.query(AuditLog).order_by(AuditLog.id)]
        assert nomes == ["buscar_cliente_por_cnpj", "solicitar_cadastro_cliente"]


def test_atualizacao_de_oportunidade_enfileira_omie_update(session_factory):
    responses = [
        FakeResponse(
            [
                ToolUseBlock(
                    "t1",
                    "solicitar_atualizacao_oportunidade",
                    {"codigo_oportunidade": 555, "campos": {"fasesStatus": {"nCodFase": 3}}},
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("Atualização enfileirada.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_demand("Mova a oportunidade 555 para a etapa 3", trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        approval = s.query(Approval).one()
        assert approval.action_type == "omie_update"
        assert approval.payload_json["entity"] == "opportunity"
        assert approval.payload_json["data"]["identificacao"]["nCodOp"] == 555
        assert approval.status == "pending"


def test_crm_agent_nao_tem_ferramenta_de_escrita_direta_nem_delecao(session_factory):
    agent = make_agent(session_factory, responses=[])
    nomes = set(agent._tools_by_name)
    # só ferramentas de leitura e de "solicitar_*" (que enfileiram)
    assert {"solicitar_cadastro_cliente", "solicitar_atualizacao_cliente",
            "solicitar_cadastro_oportunidade", "solicitar_atualizacao_oportunidade"} <= nomes
    assert not nomes & {"criar_cliente", "atualizar_cliente", "excluir_cliente",
                        "deletar_oportunidade", "create_client"}
    # nenhuma ferramenta de escrita executa direto: todas as is_write enfileiram
    for nome in nomes:
        if nome.startswith("solicitar_"):
            assert agent._tools_by_name[nome].is_write is True
