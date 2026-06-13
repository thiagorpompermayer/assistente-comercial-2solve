"""advisor_agent: lê resumos do banco e registra análise priorizada."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.db.models import AdvisorAnalysis, Alert, AuditLog, PipelineCache


def make_agent(session_factory, responses):
    from src.agents.advisor_agent import AdvisorAgent

    return AdvisorAgent(session_factory, client=FakeAnthropic(responses))


def test_advisor_consulta_resumos_e_registra_analise(session_factory):
    with session_factory() as s:
        s.add_all([
            PipelineCache(omie_id="1", etapa="Proposta enviada", valor=150_000.0),
            Alert(kind="proposal_stale", title="Usina X parada", detail="14 dias",
                  status="open", severity="high"),
        ])
        s.commit()

    recomendacoes = [
        {"prioridade": "alta", "titulo": "Reativar Usina X",
         "porque": "Proposta de R$150k parada há 14 dias",
         "proximo_passo": "Ligar para o contato e propor visita esta semana"},
    ]
    responses = [
        FakeResponse([ToolUseBlock("t1", "resumo_pipeline", {})], "tool_use"),
        FakeResponse([ToolUseBlock("t2", "resumo_operacao", {"dias": 30})], "tool_use"),
        FakeResponse([ToolUseBlock("t3", "listar_alertas_abertos", {})], "tool_use"),
        FakeResponse(
            [ToolUseBlock("t4", "registrar_analise",
                          {"resumo": "Pipeline concentrado em proposta enviada; "
                           "R$150k em risco.", "recomendacoes": recomendacoes})],
            "tool_use",
        ),
        FakeResponse([TextBlock("Foco da semana: reativar a Usina X.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_analysis(trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        analysis = s.query(AdvisorAnalysis).one()
        assert analysis.run_id == result.run_id
        assert "R$150k" in analysis.summary
        assert len(analysis.recommendations_json) == 1
        assert analysis.recommendations_json[0]["prioridade"] == "alta"

        # consultou os resumos via ferramentas (leitura do banco), registrou (write)
        tools = [a.tool_name for a in s.query(AuditLog).order_by(AuditLog.id)]
        assert tools == ["resumo_pipeline", "resumo_operacao",
                         "listar_alertas_abertos", "registrar_analise"]
        write = s.query(AuditLog).filter_by(tool_name="registrar_analise").one()
        assert write.is_write is True


def test_advisor_usa_modelo_de_raciocinio_pesado(session_factory):
    from src.config import get_settings

    agent = make_agent(session_factory, responses=[])
    # CLAUDE.md: análises do advisor usam o modelo de proposta (Opus), não o de rotina
    assert agent._model == get_settings().claude_model_proposal
