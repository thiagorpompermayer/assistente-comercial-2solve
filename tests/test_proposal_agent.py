"""proposal_agent: consulta Omie, gera PPTX e publica no OneDrive."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.proposal_agent import ProposalAgent
from src.db.models import AuditLog, Proposal

CONTEUDO = {
    "cliente": "Usina X",
    "projeto": "Adequação de Instrumentação",
    "titulo": "Modernização da medição fiscal",
    "numero": "2002000",
    "escopo": ["Levantamento de campo"],
    "itens": [
        {"descricao": "Gateway LoRaWAN", "quantidade": 1, "valor_unitario": 12512.74}
    ],
    "prazo_entrega": "90 dias",
    "condicoes_pagamento": ["28 dias após faturamento"],
}


class StubOmie:
    def get_client(self, client_id):
        return {
            "codigo_cliente_omie": client_id,
            "razao_social": "USINA X S.A.",
            "nome_fantasia": "Usina X",
            "cnpj_cpf": "00.000.000/0001-00",
        }


class StubGraph:
    def __init__(self):
        self.uploads = []

    def upload_file(self, remote_path, content):
        self.uploads.append((remote_path, len(content)))
        return {"id": "od-1", "webUrl": "https://onedrive/x/proposta.pptx"}


def test_geracao_completa_atualiza_proposta(session_factory, tmp_path):
    with session_factory() as s:
        proposal = Proposal(title="Proposta Usina X", omie_client_id=42,
                            input_json={"cliente": "Usina X"})
        s.add(proposal)
        s.commit()
        proposal_id = proposal.id

    graph = StubGraph()
    responses = [
        FakeResponse(
            [ToolUseBlock("t1", "consultar_cliente_omie", {"codigo_cliente_omie": 42})],
            "tool_use",
        ),
        FakeResponse([ToolUseBlock("t2", "gerar_pptx", CONTEUDO)], "tool_use"),
        FakeResponse([ToolUseBlock("t3", "salvar_onedrive", {})], "tool_use"),
        FakeResponse([TextBlock("Proposta gerada e publicada.")], "end_turn"),
    ]
    agent = ProposalAgent(
        session_factory,
        omie=StubOmie(),
        graph=graph,
        client=FakeAnthropic(responses),
        output_dir=tmp_path,
    )

    result = agent.run_generation(proposal_id)

    assert result.status == "done"
    with session_factory() as s:
        proposal = s.get(Proposal, proposal_id)
        assert proposal.status == "generated"
        assert proposal.pptx_path and proposal.pptx_path.endswith(
            "Proposta_2Solve_Usina_X_2002000_Rev0.pptx"
        )
        assert proposal.onedrive_url == "https://onedrive/x/proposta.pptx"

        nomes = [a.tool_name for a in s.query(AuditLog).order_by(AuditLog.id)]
        assert nomes == ["consultar_cliente_omie", "gerar_pptx", "salvar_onedrive"]

    remote_path, size = graph.uploads[0]
    assert remote_path.endswith("Proposta_2Solve_Usina_X_2002000_Rev0.pptx")
    assert size > 10_000  # PPTX real foi enviado


def test_salvar_onedrive_antes_de_gerar_vira_erro_de_tool(session_factory, tmp_path):
    with session_factory() as s:
        proposal = Proposal(title="P", input_json={})
        s.add(proposal)
        s.commit()
        proposal_id = proposal.id

    responses = [
        FakeResponse([ToolUseBlock("t1", "salvar_onedrive", {})], "tool_use"),
        FakeResponse([TextBlock("Preciso gerar o PPTX antes.")], "end_turn"),
    ]
    agent = ProposalAgent(
        session_factory,
        omie=StubOmie(),
        graph=StubGraph(),
        client=FakeAnthropic(responses),
        output_dir=tmp_path,
    )

    result = agent.run_generation(proposal_id)

    assert result.status == "done"  # erro voltou como tool_result, loop seguiu
    tool_result = agent._client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "gere o PPTX" in tool_result["content"]


def test_falha_total_marca_proposta_error(session_factory, tmp_path):
    with session_factory() as s:
        proposal = Proposal(title="P", input_json={})
        s.add(proposal)
        s.commit()
        proposal_id = proposal.id

    class ClienteQuebrado:
        class messages:
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError("pane")

    agent = ProposalAgent(
        session_factory,
        omie=StubOmie(),
        graph=StubGraph(),
        client=ClienteQuebrado(),
        output_dir=tmp_path,
    )

    result = agent.run_generation(proposal_id)

    assert result.status == "error"
    with session_factory() as s:
        assert s.get(Proposal, proposal_id).status == "error"
