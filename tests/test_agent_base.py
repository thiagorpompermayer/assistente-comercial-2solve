"""Loop de tool use cru: despacho, erro-como-tool-result, auditoria e tokens."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.base import BaseAgent, Tool
from src.db.models import AgentRun, AuditLog

ECHO_SCHEMA = {"type": "object", "properties": {"msg": {"type": "string"}}}


class AgenteTeste(BaseAgent):
    name = "teste"
    system_prompt = "Agente de teste."


def make_agent(session_factory, responses, tools):
    return AgenteTeste(session_factory, tools, client=FakeAnthropic(responses))


def test_despacha_tool_e_retorna_texto_final(session_factory):
    tools = [Tool("echo", "ecoa", ECHO_SCHEMA, handler=lambda msg: {"echo": msg})]
    responses = [
        FakeResponse([ToolUseBlock("tu1", "echo", {"msg": "oi"})], "tool_use"),
        FakeResponse([TextBlock("pronto")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses, tools)

    result = agent.run_demand("ecoa oi")

    assert result.status == "done"
    assert result.output_text == "pronto"
    with session_factory() as s:
        run = s.get(AgentRun, result.run_id)
        assert run.status == "done"
        assert run.tokens_in == 20 and run.tokens_out == 10  # 2 chamadas
        audit = s.query(AuditLog).filter_by(run_id=run.id).all()
        assert len(audit) == 1
        assert audit[0].tool_name == "echo"
        assert audit[0].input_json == {"msg": "oi"}


def test_erro_de_tool_volta_como_tool_result_sem_derrubar_loop(session_factory):
    def explode(**_kwargs):
        raise ValueError("boom")

    tools = [Tool("quebra", "sempre falha", {"type": "object"}, handler=explode)]
    responses = [
        FakeResponse([ToolUseBlock("tu1", "quebra", {})], "tool_use"),
        FakeResponse([TextBlock("contornei o erro")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses, tools)

    result = agent.run_demand("tenta")

    assert result.status == "done"
    # o segundo create recebeu o tool_result com is_error=True
    segunda_chamada = agent._client.messages.calls[1]
    tool_result = segunda_chamada["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "boom" in tool_result["content"]
    with session_factory() as s:
        audit = s.query(AuditLog).one()
        assert audit.output_json["is_error"] is True


def test_ferramenta_desconhecida_vira_erro_de_tool(session_factory):
    responses = [
        FakeResponse([ToolUseBlock("tu1", "nao_existe", {})], "tool_use"),
        FakeResponse([TextBlock("ok")], "end_turn"),
    ]
    agent = make_agent(session_factory, responses, tools=[])

    result = agent.run_demand("usa tool fantasma")

    assert result.status == "done"
    tool_result = agent._client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "desconhecida" in tool_result["content"]


def test_falha_inesperada_registra_run_error(session_factory):
    class ClienteQuebrado:
        class messages:
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError("pane total")

    agent = AgenteTeste(session_factory, tools=[], client=ClienteQuebrado())

    result = agent.run_demand("qualquer coisa")

    assert result.status == "error"
    with session_factory() as s:
        run = s.get(AgentRun, result.run_id)
        assert run.status == "error"
        assert "pane total" in run.error
