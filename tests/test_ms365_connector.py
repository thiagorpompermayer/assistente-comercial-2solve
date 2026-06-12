import httpx
import pytest
import respx

from src.connectors.ms365 import GRAPH_BASE, GraphClient, GraphError

MAILBOX = "comercial@2solve.com"


def make_client() -> GraphClient:
    return GraphClient(mailbox=MAILBOX, token_provider=lambda: "tok-teste")


@respx.mock
def test_list_messages_envia_token_e_parseia_value():
    route = respx.get(f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(
            200, json={"value": [{"id": "m1", "subject": "Pedido de orçamento"}]}
        )
    )
    messages = make_client().list_messages(top=5)

    assert messages == [{"id": "m1", "subject": "Pedido de orçamento"}]
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok-teste"
    assert request.url.params["$top"] == "5"


@respx.mock
def test_list_calendar_events():
    respx.get(f"{GRAPH_BASE}/users/{MAILBOX}/calendarView").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "e1", "subject": "Visita"}]})
    )
    events = make_client().list_calendar_events("2026-06-01T00:00:00Z", "2026-06-15T00:00:00Z")
    assert events[0]["id"] == "e1"


@respx.mock
def test_erro_http_vira_graph_error_com_mensagem():
    respx.get(f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(
            403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied"}}
        )
    )
    with pytest.raises(GraphError, match="403.*Access is denied"):
        make_client().list_messages()
