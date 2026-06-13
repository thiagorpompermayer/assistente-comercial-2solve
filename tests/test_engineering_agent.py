"""engineering_agent: registra artefatos técnicos (escrita local auditada)."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.engineering_agent import EngineeringAgent
from src.db.models import AuditLog, EngineeringArtifact, Proposal


def make_agent(session_factory, responses):
    return EngineeringAgent(session_factory, client=FakeAnthropic(responses))


def test_registra_lista_e_fluxograma_vinculados_a_proposta(session_factory):
    with session_factory() as s:
        proposal = Proposal(title="Proposta Usina X", input_json={})
        s.add(proposal)
        s.commit()
        proposal_id = proposal.id

    responses = [
        FakeResponse(
            [ToolUseBlock("t1", "analisar_tag_isa", {"tag": "FT-101"})], "tool_use"
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "t2",
                    "registrar_lista_instrumentos",
                    {
                        "titulo": "Lista de instrumentos — Área 100",
                        "instrumentos": [
                            {"tag": "FT-101", "servico": "Vazão de óleo",
                             "sinal": "4-20 mA"},
                            {"tag": "PIC-205", "servico": "Controle de pressão"},
                        ],
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "t3",
                    "gerar_fluxograma",
                    {
                        "titulo": "PFD simplificado",
                        "nos": [
                            {"id": "TQ01", "label": "Tanque", "shape": "round"},
                            {"id": "P01", "label": "Bomba"},
                        ],
                        "conexoes": [{"from": "TQ01", "to": "P01", "label": "óleo"}],
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("2 artefatos registrados.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_demand(
        "Monte a lista de instrumentos e o PFD da área 100", proposal_id=proposal_id
    )

    assert result.status == "done"
    with session_factory() as s:
        artifacts = s.query(EngineeringArtifact).order_by(EngineeringArtifact.id).all()
        kinds = [a.kind for a in artifacts]
        assert kinds == ["instrument_list", "flowchart"]
        assert all(a.proposal_id == proposal_id for a in artifacts)
        assert all(a.run_id == result.run_id for a in artifacts)

        lista = artifacts[0]
        assert lista.content_json["total"] == 2
        assert lista.content_json["instrumentos"][0]["tag_valida"] is True

        flow = artifacts[1]
        assert flow.content_text.startswith("flowchart LR")
        assert "TQ01" in flow.content_text

        tools = {a.tool_name for a in s.query(AuditLog).all()}
        assert tools == {"analisar_tag_isa", "registrar_lista_instrumentos",
                         "gerar_fluxograma"}
        writes = {
            a.tool_name for a in s.query(AuditLog).filter_by(is_write=True).all()
        }
        assert writes == {"registrar_lista_instrumentos", "gerar_fluxograma"}


def test_memorial_sem_proposta_fica_com_proposal_id_nulo(session_factory):
    responses = [
        FakeResponse(
            [
                ToolUseBlock(
                    "t1",
                    "registrar_memorial",
                    {"titulo": "Memorial — malha de nível",
                     "markdown": "## Filosofia de controle\nLIC-100 atua na LV-100."},
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("Memorial registrado.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_demand("Escreva o memorial da malha de nível")

    assert result.status == "done"
    with session_factory() as s:
        artifact = s.query(EngineeringArtifact).one()
        assert artifact.kind == "memorial"
        assert artifact.proposal_id is None
        assert "LIC-100" in artifact.content_text
