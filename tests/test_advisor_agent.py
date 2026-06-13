"""advisor_agent: coleta rotineira (Sonnet) + síntese pesada (Opus), uma só vez."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.config import get_settings
from src.db.models import AdvisorAnalysis, Alert, AuditLog, PipelineCache


def make_agent(session_factory, responses):
    from src.agents.advisor_agent import AdvisorAgent

    return AdvisorAgent(session_factory, client=FakeAnthropic(responses))


def _model_of(call) -> str:
    return call["model"]


def _tool_names(call) -> set[str]:
    return {t["name"] for t in call.get("tools", [])}


def test_advisor_coleta_em_sonnet_e_sintetiza_em_opus(session_factory):
    settings = get_settings()
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
        # --- loop de coleta (modelo rotineiro) ---
        FakeResponse([ToolUseBlock("t1", "resumo_pipeline", {})], "tool_use"),
        FakeResponse([ToolUseBlock("t2", "resumo_operacao", {"dias": 30})], "tool_use"),
        FakeResponse([ToolUseBlock("t3", "listar_alertas_abertos", {})], "tool_use"),
        FakeResponse(
            [ToolUseBlock("t4", "gerar_analise_priorizada",
                          {"foco": "proposta enviada"})],
            "tool_use",
        ),
        # --- chamada de raciocínio pesado, dentro do handler (modelo Opus) ---
        FakeResponse(
            [ToolUseBlock("h1", "entregar_analise",
                          {"resumo": "Pipeline concentrado em proposta enviada; "
                           "R$150k em risco.", "recomendacoes": recomendacoes})],
            "tool_use",
        ),
        # --- fechamento do loop rotineiro ---
        FakeResponse([TextBlock("Foco da semana: reativar a Usina X.")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)

    result = agent.run_analysis(trigger="api")

    assert result.status == "done"

    # análise registrada
    with session_factory() as s:
        analysis = s.query(AdvisorAnalysis).one()
        assert analysis.run_id == result.run_id
        assert "R$150k" in analysis.summary
        assert analysis.recommendations_json[0]["prioridade"] == "alta"

        # auditoria: só as ferramentas do loop (entregar_analise é interna)
        tools = [a.tool_name for a in s.query(AuditLog).order_by(AuditLog.id)]
        assert tools == ["resumo_pipeline", "resumo_operacao",
                         "listar_alertas_abertos", "gerar_analise_priorizada"]
        assert s.query(AuditLog).filter_by(
            tool_name="gerar_analise_priorizada"
        ).one().is_write is True

    # tiering de modelo: coleta em Sonnet, síntese em Opus
    calls = agent._client.messages.calls
    gather_calls = [c for c in calls if "entregar_analise" not in _tool_names(c)]
    deep_calls = [c for c in calls if "entregar_analise" in _tool_names(c)]
    assert len(deep_calls) == 1
    assert all(_model_of(c) == settings.claude_model for c in gather_calls)
    assert _model_of(deep_calls[0]) == settings.claude_model_proposal


def test_advisor_modelos_rotina_e_pesado_distintos(session_factory):
    settings = get_settings()
    agent = make_agent(session_factory, responses=[])
    assert agent._model == settings.claude_model  # rotina = Sonnet
    assert agent._heavy_model == settings.claude_model_proposal  # pesado = Opus
    assert agent._model != agent._heavy_model


def test_reason_deep_fallback_quando_modelo_responde_texto(session_factory):
    # se o Opus responder texto em vez de usar a ferramenta, não quebra
    responses = [
        FakeResponse([ToolUseBlock("t1", "gerar_analise_priorizada", {})], "tool_use"),
        FakeResponse([TextBlock("Análise em texto livre, sem ferramenta.")], "end_turn"),
        FakeResponse([TextBlock("ok")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses)
    result = agent.run_analysis(trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        analysis = s.query(AdvisorAnalysis).one()
        assert "texto livre" in analysis.summary
        assert analysis.recommendations_json == []
