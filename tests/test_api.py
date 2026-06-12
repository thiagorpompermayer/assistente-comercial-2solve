"""Testes de contrato da API REST v1."""

import pytest
from fastapi.testclient import TestClient

from src import approvals
from src.api.deps import (
    get_db,
    get_email_runner,
    get_graph_client,
    get_monitor_runner,
    get_proposal_runner,
)
from src.db.models import AgentRun, Alert, EmailTriaged, Proposal
from src.main import create_app


class StubGraph:
    def get_message(self, message_id):
        return {
            "id": message_id,
            "subject": "RE: Orçamento",
            "body": {"contentType": "text", "content": "Olá, obrigado pelo contato."},
            "toRecipients": [{"emailAddress": {"address": "joao@usinax.com"}}],
        }


@pytest.fixture()
def client(session_factory):
    app = create_app()

    def _get_db():
        with session_factory() as s:
            yield s

    def _fake_runner_dep():
        def _run(run_id: int) -> None:
            with session_factory() as s:
                run = s.get(AgentRun, run_id)
                run.status = "done"
                run.output_json = {"text": "execução fake"}
                s.commit()

        return _run

    def _fake_proposal_runner_dep():
        def _run(proposal_id: int, run_id: int) -> None:
            with session_factory() as s:
                s.get(Proposal, proposal_id).status = "generated"
                s.get(AgentRun, run_id).status = "done"
                s.commit()

        return _run

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_monitor_runner] = _fake_runner_dep
    app.dependency_overrides[get_email_runner] = _fake_runner_dep
    app.dependency_overrides[get_proposal_runner] = _fake_proposal_runner_dep
    app.dependency_overrides[get_graph_client] = lambda: StubGraph()
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolar_executors():
    snapshot = dict(approvals._EXECUTORS)
    approvals._EXECUTORS.clear()
    yield
    approvals._EXECUTORS.clear()
    approvals._EXECUTORS.update(snapshot)


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_alerts_lista_filtra_e_atualiza_status(client, session_factory):
    with session_factory() as s:
        s.add(Alert(kind="task_overdue", title="Tarefa vencida", detail="d", severity="high"))
        s.add(
            Alert(
                kind="followup_overdue",
                title="Follow-up",
                detail="d",
                status="dismissed",
            )
        )
        s.commit()

    abertos = client.get("/api/v1/alerts").json()
    assert len(abertos) == 1
    assert abertos[0]["title"] == "Tarefa vencida"

    alert_id = abertos[0]["id"]
    patched = client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "done"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"

    assert client.patch("/api/v1/alerts/9999", json={"status": "done"}).status_code == 404


def test_fluxo_de_aprovacao_via_api(client, session_factory):
    executado = {}
    approvals.register_executor("email_send")(lambda p: executado.update(p) or {"ok": True})
    with session_factory() as s:
        approval = approvals.request_approval(
            s,
            action_type="email_send",
            payload={"to": "x@y.com", "body": "olá"},
            preview_text="Enviar email para x@y.com",
        )

    pendentes = client.get("/api/v1/approvals").json()
    assert [p["id"] for p in pendentes] == [approval.id]
    assert pendentes[0]["preview_text"] == "Enviar email para x@y.com"

    aprovado = client.post(
        f"/api/v1/approvals/{approval.id}/approve", json={"decided_by": "thiago"}
    )
    assert aprovado.status_code == 200
    assert aprovado.json()["status"] == "executed"
    assert executado == {"to": "x@y.com", "body": "olá"}

    # decisão é única: segunda aprovação → 409
    de_novo = client.post(
        f"/api/v1/approvals/{approval.id}/approve", json={"decided_by": "thiago"}
    )
    assert de_novo.status_code == 409

    assert (
        client.post("/api/v1/approvals/9999/approve", json={"decided_by": "x"}).status_code
        == 404
    )


def test_rejeicao_via_api(client, session_factory):
    with session_factory() as s:
        approval = approvals.request_approval(
            s,
            action_type="omie_create",
            payload={"nome": "Cliente Novo"},
            preview_text="Criar cliente no Omie",
        )

    rejeitado = client.post(
        f"/api/v1/approvals/{approval.id}/reject",
        json={"decided_by": "ana", "reason": "dados incompletos"},
    )
    assert rejeitado.status_code == 200
    body = rejeitado.json()
    assert body["status"] == "rejected"
    assert body["reject_reason"] == "dados incompletos"


def test_emails_triados_lista_e_filtra(client, session_factory):
    with session_factory() as s:
        s.add(
            EmailTriaged(
                graph_message_id="m1",
                classification="lead",
                summary="Pedido de orçamento",
                sender="joao@usinax.com",
                subject="Orçamento",
                draft_id="draft-1",
            )
        )
        s.add(
            EmailTriaged(
                graph_message_id="m2", classification="irrelevante", summary="Spam"
            )
        )
        s.commit()

    todos = client.get("/api/v1/emails/triaged").json()
    assert len(todos) == 2

    leads = client.get("/api/v1/emails/triaged", params={"classification": "lead"}).json()
    assert len(leads) == 1
    assert leads[0]["sender"] == "joao@usinax.com"


def test_rascunho_de_email_triado(client, session_factory):
    with session_factory() as s:
        row = EmailTriaged(
            graph_message_id="m1",
            classification="lead",
            summary="x",
            draft_id="draft-1",
        )
        sem_draft = EmailTriaged(
            graph_message_id="m2", classification="irrelevante", summary="y"
        )
        s.add_all([row, sem_draft])
        s.commit()
        com_draft_id, sem_draft_id = row.id, sem_draft.id

    draft = client.get(f"/api/v1/emails/{com_draft_id}/draft")
    assert draft.status_code == 200
    body = draft.json()
    assert body["draft_id"] == "draft-1"
    assert body["to"] == ["joao@usinax.com"]
    assert "obrigado" in body["body"]

    assert client.get(f"/api/v1/emails/{sem_draft_id}/draft").status_code == 404
    assert client.get("/api/v1/emails/9999/draft").status_code == 404


def test_criar_proposta_retorna_202_e_executa(client, session_factory):
    payload = {
        "omie_client_id": 42,
        "cliente": "Usina X",
        "projeto": "Adequação",
        "title": "Proposta Usina X",
        "scope": ["Levantamento de campo"],
        "items": [{"descricao": "Gateway", "quantidade": 1, "valor_unitario": 100.0}],
        "deadline": "90 dias",
        "conditions": ["28 dias após faturamento"],
    }
    response = client.post("/api/v1/proposals", json=payload)
    assert response.status_code == 202
    body = response.json()

    detail = client.get(f"/api/v1/proposals/{body['proposal_id']}").json()
    assert detail["status"] == "generated"  # runner fake rodou no background
    assert detail["input_json"]["cliente"] == "Usina X"
    assert detail["run_id"] == body["run_id"]

    lista = client.get("/api/v1/proposals").json()
    assert len(lista) == 1


def test_download_de_proposta(client, session_factory, tmp_path):
    pptx = tmp_path / "p.pptx"
    pptx.write_bytes(b"fake-pptx")
    with session_factory() as s:
        com_arquivo = Proposal(title="A", input_json={}, pptx_path=str(pptx),
                               status="generated")
        sem_arquivo = Proposal(title="B", input_json={})
        s.add_all([com_arquivo, sem_arquivo])
        s.commit()
        ok_id, missing_id = com_arquivo.id, sem_arquivo.id

    ok = client.get(f"/api/v1/proposals/{ok_id}/download")
    assert ok.status_code == 200
    assert ok.content == b"fake-pptx"

    assert client.get(f"/api/v1/proposals/{missing_id}/download").status_code == 404
    assert client.get("/api/v1/proposals/9999/download").status_code == 404


def test_disparo_manual_da_triagem_retorna_202_e_executa(client):
    response = client.post("/api/v1/agents/email/triage")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "done"


def test_disparo_manual_do_monitor_retorna_202_e_executa(client, session_factory):
    response = client.post("/api/v1/agents/monitor/run")
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    run = client.get(f"/api/v1/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "done"  # background task do TestClient já rodou
