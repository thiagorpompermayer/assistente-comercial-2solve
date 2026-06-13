import json

import httpx
import pytest
import respx

from src.connectors.omie import OmieClient, OmieError

BASE = "https://app.omie.com.br/api/v1"


def make_client(**kwargs) -> OmieClient:
    return OmieClient(app_key="k123", app_secret="s456", retry_delays=(0, 0), **kwargs)


@respx.mock
def test_list_opportunities_envia_corpo_padrao_omie():
    route = respx.post(f"{BASE}/crm/oportunidades/").mock(
        return_value=httpx.Response(
            200, json={"total_de_registros": 1, "cadastros": [{"identificacao": {"nCodOp": 9}}]}
        )
    )
    data = make_client().list_opportunities(page=2, per_page=10)

    assert data["total_de_registros"] == 1
    body = json.loads(route.calls[0].request.content)
    assert body["call"] == "ListarOportunidades"
    assert body["app_key"] == "k123"
    assert body["param"] == [{"pagina": 2, "registros_por_pagina": 10}]


@respx.mock
def test_faultstring_vira_omie_error():
    respx.post(f"{BASE}/geral/clientes/").mock(
        return_value=httpx.Response(
            200, json={"faultcode": "SOAP-ENV:Client-101", "faultstring": "chave inválida"}
        )
    )
    with pytest.raises(OmieError, match="chave inválida"):
        make_client().list_clients()


@respx.mock
def test_get_client_consulta_por_codigo():
    route = respx.post(f"{BASE}/geral/clientes/").mock(
        return_value=httpx.Response(
            200, json={"codigo_cliente_omie": 42, "razao_social": "USINA X S.A."}
        )
    )
    data = make_client().get_client(42)
    assert data["razao_social"] == "USINA X S.A."
    body = json.loads(route.calls[0].request.content)
    assert body["call"] == "ConsultarCliente"
    assert body["param"] == [{"codigo_cliente_omie": 42}]


@respx.mock
def test_find_client_by_document_usa_filtro():
    route = respx.post(f"{BASE}/geral/clientes/").mock(
        return_value=httpx.Response(200, json={"total_de_registros": 0, "clientes_cadastro": []})
    )
    make_client().find_client_by_document("10.821.258/0001-02")
    body = json.loads(route.calls[0].request.content)
    assert body["call"] == "ListarClientes"
    assert body["param"][0]["clientesFiltro"] == {"cnpj_cpf": "10.821.258/0001-02"}


@respx.mock
def test_create_client_chama_incluircliente():
    route = respx.post(f"{BASE}/geral/clientes/").mock(
        return_value=httpx.Response(200, json={"codigo_cliente_omie": 999, "codigo_status": "0"})
    )
    data = make_client().create_client({"razao_social": "USINA X", "cnpj_cpf": "00"})
    assert data["codigo_cliente_omie"] == 999
    body = json.loads(route.calls[0].request.content)
    assert body["call"] == "IncluirCliente"
    assert body["param"] == [{"razao_social": "USINA X", "cnpj_cpf": "00"}]


@respx.mock
def test_update_opportunity_chama_alteraroportunidade():
    route = respx.post(f"{BASE}/crm/oportunidades/").mock(
        return_value=httpx.Response(200, json={"nCodOp": 5, "cCodStatus": "0"})
    )
    make_client().update_opportunity({"identificacao": {"nCodOp": 5}})
    body = json.loads(route.calls[0].request.content)
    assert body["call"] == "AlterarOportunidade"


@respx.mock
def test_retry_em_500_e_sucesso_na_segunda():
    route = respx.post(f"{BASE}/crm/tarefas/")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"total_de_registros": 0, "cadastros": []}),
    ]
    data = make_client().list_tasks()
    assert data["cadastros"] == []
    assert route.call_count == 2


@respx.mock
def test_esgotar_retries_vira_omie_error():
    respx.post(f"{BASE}/crm/tarefas/").mock(return_value=httpx.Response(503))
    with pytest.raises(OmieError, match="indisponível após retries"):
        make_client().list_tasks()
