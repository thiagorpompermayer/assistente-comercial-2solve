"""monitor_agent: leitura Omie/calendário + criação de alerta auditada."""

from fakes import FakeAnthropic, FakeResponse, TextBlock, ToolUseBlock

from src.agents.monitor_agent import MonitorAgent, build_overdue_demand
from src.db.models import Alert, AuditLog


class StubOmie:
    def list_opportunities(self, page=1, per_page=50):
        return {
            "total_de_registros": 1,
            "cadastros": [
                {
                    "identificacao": {"nCodOp": 777, "cDesOp": "Adequação Usina X"},
                    "previsao": {"dDataPrevisao": "2026-05-20"},
                }
            ],
        }

    def list_tasks(self, page=1, per_page=50):
        return {"total_de_registros": 0, "cadastros": []}


class StubGraph:
    def list_calendar_events(self, start_iso, end_iso):
        return []


def test_varredura_cria_alerta_e_audita(session_factory):
    responses = [
        FakeResponse(
            [ToolUseBlock("tu1", "omie_listar_oportunidades", {"pagina": 1})], "tool_use"
        ),
        FakeResponse(
            [
                ToolUseBlock(
                    "tu2",
                    "criar_alerta",
                    {
                        "kind": "followup_overdue",
                        "title": "Adequação Usina X parada há 23 dias",
                        "detail": "Oportunidade 777 sem movimento desde 2026-05-20. "
                        "Sugestão: ligar para o contato e reagendar visita.",
                        "severity": "high",
                        "entity_ref": "777",
                    },
                )
            ],
            "tool_use",
        ),
        FakeResponse([TextBlock("1 alerta criado.")], "end_turn"),
    ]
    agent = MonitorAgent(
        session_factory,
        omie=StubOmie(),
        graph=StubGraph(),
        client=FakeAnthropic(responses),
    )

    result = agent.run_overdue_scan(trigger="api")

    assert result.status == "done"
    with session_factory() as s:
        alert = s.query(Alert).one()
        assert alert.run_id == result.run_id
        assert alert.kind == "followup_overdue"
        assert alert.severity == "high"
        assert alert.entity_ref == "777"
        assert alert.status == "open"

        nomes = {a.tool_name for a in s.query(AuditLog).all()}
        assert nomes == {"omie_listar_oportunidades", "criar_alerta"}
        criar = s.query(AuditLog).filter_by(tool_name="criar_alerta").one()
        assert criar.is_write is True


def test_demanda_inclui_data_de_hoje():
    from datetime import date

    demand = build_overdue_demand(date(2026, 6, 12))
    assert "2026-06-12" in demand
