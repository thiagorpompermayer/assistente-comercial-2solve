"""Agregações de dashboard (offline) e sync do pipeline a partir do Omie."""

from src.dashboard import operations_summary, pipeline_summary, sync_pipeline_cache
from src.db.models import (
    Alert,
    Approval,
    EmailTriaged,
    PipelineCache,
    Proposal,
)


def test_pipeline_summary_agrega_por_estagio_e_ticket_medio(session):
    session.add_all([
        PipelineCache(omie_id="1", etapa="Proposta enviada", valor=100_000.0),
        PipelineCache(omie_id="2", etapa="Proposta enviada", valor=60_000.0),
        PipelineCache(omie_id="3", etapa="Qualificação", valor=40_000.0),
    ])
    session.commit()

    summary = pipeline_summary(session)

    assert summary["total_oportunidades"] == 3
    assert summary["valor_total"] == 200_000.0
    assert summary["ticket_medio"] == round(200_000 / 3, 2)
    # ordenado por valor desc: "Proposta enviada" (160k) primeiro
    assert summary["estagios"][0]["etapa"] == "Proposta enviada"
    assert summary["estagios"][0]["quantidade"] == 2
    assert summary["estagios"][0]["valor_total"] == 160_000.0


def test_pipeline_summary_vazio():
    # sem dados, não quebra (ticket médio 0)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.db.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        summary = pipeline_summary(s)
        assert summary["total_oportunidades"] == 0
        assert summary["ticket_medio"] == 0.0


def test_operations_summary_conta_filas_e_classificacoes(session):
    session.add_all([
        EmailTriaged(graph_message_id="m1", classification="lead", summary="x"),
        EmailTriaged(graph_message_id="m2", classification="lead", summary="y"),
        EmailTriaged(graph_message_id="m3", classification="fornecedor", summary="z"),
        Approval(action_type="email_send", payload_json={}, status="pending"),
        Approval(action_type="email_send", payload_json={}, status="executed"),
        Approval(action_type="omie_create", payload_json={}, status="rejected"),
        Alert(kind="task_overdue", title="t", detail="d", status="open"),
        Proposal(title="P", input_json={}, status="generated"),
    ])
    session.commit()

    ops = operations_summary(session)

    assert ops["emails_triados_periodo"] == 3
    assert ops["emails_por_classificacao"]["lead"] == 2
    assert ops["aprovacoes"]["fila_pendente"] == 1
    assert ops["aprovacoes"]["executadas"] == 1
    assert ops["aprovacoes"]["rejeitadas"] == 1
    assert ops["alertas_abertos"] == 1
    assert ops["propostas_por_status"]["generated"] == 1


class StubOmie:
    def __init__(self):
        self.pages_requested = []

    def list_opportunity_stages(self):
        return {"cadastro": [
            {"nCodEtapa": 10, "cDescricao": "Qualificação"},
            {"nCodEtapa": 20, "cDescricao": "Proposta enviada"},
        ]}

    def list_opportunities(self, page=1):
        self.pages_requested.append(page)
        if page == 1:
            return {
                "total_de_paginas": 2,
                "cadastros": [
                    {"identificacao": {"nCodOp": 777, "cDesOp": "Usina X",
                                       "nCodClien": 42},
                     "ticket": {"nValorOp": 150_000.0},
                     "fasesStatus": {"nCodFase": 20}},
                ],
            }
        return {
            "total_de_paginas": 2,
            "cadastros": [
                {"identificacao": {"nCodOp": 888, "cDesOp": "Usina Y", "nCodClien": 43},
                 "ticket": {"nValorOp": 80_000.0},
                 "fasesStatus": {"nCodFase": 10}},
            ],
        }


def test_sync_pipeline_cache_pagina_e_resolve_etapa(session):
    omie = StubOmie()
    result = sync_pipeline_cache(session, omie=omie)

    assert result["sincronizadas"] == 2
    assert omie.pages_requested == [1, 2]  # paginou até o fim

    rows = {r.omie_id: r for r in session.query(PipelineCache).all()}
    assert rows["777"].etapa == "Proposta enviada"  # código resolvido para nome
    assert rows["777"].valor == 150_000.0
    assert rows["777"].titulo == "Usina X"
    assert rows["777"].cliente_ref == "42"
    assert rows["888"].etapa == "Qualificação"


def test_sync_upsert_atualiza_existente(session):
    session.add(PipelineCache(omie_id="777", etapa="(antigo)", valor=1.0))
    session.commit()

    sync_pipeline_cache(session, omie=StubOmie())

    rows = session.query(PipelineCache).filter_by(omie_id="777").all()
    assert len(rows) == 1  # não duplicou
    assert rows[0].valor == 150_000.0


def test_sync_resiliente_a_falha_nas_etapas(session):
    class OmieSemEtapas(StubOmie):
        def list_opportunity_stages(self):
            raise RuntimeError("403")

    sync_pipeline_cache(session, omie=OmieSemEtapas())
    row = session.query(PipelineCache).filter_by(omie_id="777").one()
    assert row.etapa == "Etapa 20"  # fallback para o código quando etapas falham
