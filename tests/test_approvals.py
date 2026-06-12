"""Invariantes do portão de aprovação (regras duras 1 e 2)."""

import pytest

from src import approvals
from src.db.models import ActionFlag, AuditLog


@pytest.fixture(autouse=True)
def isolar_executors():
    snapshot = dict(approvals._EXECUTORS)
    approvals._EXECUTORS.clear()
    yield
    approvals._EXECUTORS.clear()
    approvals._EXECUTORS.update(snapshot)


def pedir(session, action_type="email_send", payload=None):
    return approvals.request_approval(
        session,
        action_type=action_type,
        payload=payload or {"to": "cliente@x.com", "body": "olá"},
        preview_text="Enviar email para cliente@x.com",
    )


def test_escrita_externa_nasce_pendente(session):
    approval = pedir(session)
    assert approval.status == "pending"
    assert approval.decided_by is None


def test_flag_ligada_auto_executa_com_payload_exato(session):
    session.add(ActionFlag(action_type="email_send", auto_execute=True))
    session.commit()
    recebido = {}
    approvals.register_executor("email_send")(lambda p: recebido.update(p) or {"ok": True})

    approval = pedir(session, payload={"to": "a@b.com", "body": "x"})

    assert approval.status == "executed"
    assert approval.decided_by == "auto-flag"
    assert recebido == {"to": "a@b.com", "body": "x"}


def test_delecao_nunca_auto_executa_mesmo_com_flag(session):
    session.add(ActionFlag(action_type="email_delete", auto_execute=True))
    session.commit()
    approvals.register_executor("email_delete")(lambda p: {"ok": True})

    approval = pedir(session, action_type="email_delete")

    assert approval.status == "pending"  # regra dura 1


def test_aprovar_executa_payload_congelado_e_audita(session):
    executado = {}
    approvals.register_executor("email_send")(lambda p: executado.update(p) or {"id": "m1"})
    approval = pedir(session, payload={"to": "a@b.com", "body": "original"})

    result = approvals.approve(session, approval.id, decided_by="thiago")

    assert result.status == "executed"
    assert result.decided_by == "thiago"
    assert executado == {"to": "a@b.com", "body": "original"}
    audit = session.query(AuditLog).filter_by(approval_id=approval.id).one()
    assert audit.is_write is True
    assert audit.tool_name == "approval:email_send"


def test_aprovar_duas_vezes_falha(session):
    approvals.register_executor("email_send")(lambda p: {"ok": True})
    approval = pedir(session)
    approvals.approve(session, approval.id, decided_by="thiago")

    with pytest.raises(approvals.ApprovalStateError):
        approvals.approve(session, approval.id, decided_by="thiago")


def test_rejeitar(session):
    approval = pedir(session)
    result = approvals.reject(session, approval.id, decided_by="ana", reason="tom errado")
    assert result.status == "rejected"
    assert result.reject_reason == "tom errado"


def test_falha_do_executor_marca_failed_sem_silenciar(session):
    def explode(_payload):
        raise RuntimeError("API externa fora do ar")

    approvals.register_executor("email_send")(explode)
    approval = pedir(session)
    result = approvals.approve(session, approval.id, decided_by="thiago")

    assert result.status == "failed"
    assert "API externa fora do ar" in result.error


def test_sem_executor_registrado_marca_failed(session):
    approval = pedir(session, action_type="omie_update")
    result = approvals.approve(session, approval.id, decided_by="thiago")
    assert result.status == "failed"
    assert "nenhum executor" in result.error
