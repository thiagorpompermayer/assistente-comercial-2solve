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
def test_create_reply_draft_envia_comment():
    route = respx.post(f"{GRAPH_BASE}/users/{MAILBOX}/messages/m1/createReply").mock(
        return_value=httpx.Response(201, json={"id": "draft-1", "subject": "RE: Orçamento"})
    )
    draft = make_client().create_reply_draft("m1", "Olá, segue retorno.")
    assert draft["id"] == "draft-1"
    import json

    assert json.loads(route.calls[0].request.content) == {"comment": "Olá, segue retorno."}


@respx.mock
def test_create_forward_draft_monta_destinatarios():
    route = respx.post(f"{GRAPH_BASE}/users/{MAILBOX}/messages/m1/createForward").mock(
        return_value=httpx.Response(201, json={"id": "draft-2"})
    )
    make_client().create_forward_draft("m1", to=["eng@2solve.com"], comment="Para análise")
    import json

    body = json.loads(route.calls[0].request.content)
    assert body["toRecipients"] == [{"emailAddress": {"address": "eng@2solve.com"}}]


@respx.mock
def test_send_draft_aceita_resposta_vazia():
    respx.post(f"{GRAPH_BASE}/users/{MAILBOX}/messages/draft-1/send").mock(
        return_value=httpx.Response(202)
    )
    assert make_client().send_draft("draft-1") is None


@respx.mock
def test_move_to_deleted_e_reversivel():
    route = respx.post(f"{GRAPH_BASE}/users/{MAILBOX}/messages/m9/move").mock(
        return_value=httpx.Response(201, json={"id": "m9-novo"})
    )
    moved = make_client().move_to_deleted("m9")
    assert moved["id"] == "m9-novo"
    import json

    assert json.loads(route.calls[0].request.content) == {"destinationId": "deleteditems"}


@respx.mock
def test_erro_http_vira_graph_error_com_mensagem():
    respx.get(f"{GRAPH_BASE}/users/{MAILBOX}/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(
            403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied"}}
        )
    )
    with pytest.raises(GraphError, match="403.*Access is denied"):
        make_client().list_messages()
