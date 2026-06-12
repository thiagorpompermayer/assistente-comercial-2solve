"""Microsoft Graph: mail (leitura, rascunhos, envio, exclusão) e calendário.

Autenticação app-only (client credentials) via MSAL, escopo .default.
Menor privilégio: Mail.ReadWrite + Mail.Send + Calendars.Read, restritos à
caixa comercial por Application Access Policy (docs/02-arquitetura.md §5).

ATENÇÃO (regras duras 1 e 2): `send_draft` e `move_to_deleted` só podem ser
chamados pelos executores do portão de aprovação (src/executors.py) — nunca
diretamente por ferramenta de agente. Rascunhos podem ser criados livremente
(ficam na pasta Drafts, nada chega ao cliente).

`token_provider` é injetável para testes (evita MSAL real).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from src.config import get_settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

MESSAGE_FIELDS = "id,subject,from,receivedDateTime,bodyPreview,isRead"
EVENT_FIELDS = "id,subject,start,end,organizer,attendees"


class GraphError(RuntimeError):
    pass


class GraphClient:
    def __init__(
        self,
        mailbox: str | None = None,
        http: httpx.Client | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        settings = get_settings()
        self._mailbox = mailbox or settings.ms_mailbox
        self._http = http or httpx.Client(timeout=30.0)
        self._token_provider = token_provider or self._msal_token
        self._msal_app: Any = None

    def _msal_token(self) -> str:
        import msal  # import tardio: testes não precisam de MSAL

        settings = get_settings()
        if self._msal_app is None:
            self._msal_app = msal.ConfidentialClientApplication(
                client_id=settings.ms_client_id,
                client_credential=settings.ms_client_secret,
                authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
            )
        result = self._msal_app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise GraphError(
                f"falha ao obter token: {result.get('error')} — "
                f"{result.get('error_description')}"
            )
        return result["access_token"]

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        response = self._http.request(
            method,
            f"{GRAPH_BASE}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self._token_provider()}"},
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except ValueError:
                detail = response.text
            raise GraphError(f"Graph HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self._request("GET", path, params=params)
        assert data is not None
        return data

    # ----- leituras -----

    def list_messages(self, folder: str = "inbox", top: int = 25) -> list[dict[str, Any]]:
        data = self._get(
            f"/users/{self._mailbox}/mailFolders/{folder}/messages",
            params={"$top": top, "$select": MESSAGE_FIELDS, "$orderby": "receivedDateTime desc"},
        )
        return data.get("value", [])

    def list_calendar_events(self, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
        data = self._get(
            f"/users/{self._mailbox}/calendarView",
            params={
                "startDateTime": start_iso,
                "endDateTime": end_iso,
                "$select": EVENT_FIELDS,
                "$orderby": "start/dateTime",
            },
        )
        return data.get("value", [])

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self._get(
            f"/users/{self._mailbox}/messages/{message_id}",
            params={"$select": f"{MESSAGE_FIELDS},body,toRecipients,ccRecipients"},
        )

    # ----- rascunhos (livres — nada chega ao cliente) -----

    def create_reply_draft(
        self, message_id: str, comment: str, reply_all: bool = False
    ) -> dict[str, Any]:
        action = "createReplyAll" if reply_all else "createReply"
        draft = self._request(
            "POST",
            f"/users/{self._mailbox}/messages/{message_id}/{action}",
            json={"comment": comment},
        )
        assert draft is not None
        return draft

    def create_forward_draft(
        self, message_id: str, to: list[str], comment: str = ""
    ) -> dict[str, Any]:
        draft = self._request(
            "POST",
            f"/users/{self._mailbox}/messages/{message_id}/createForward",
            json={
                "comment": comment,
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            },
        )
        assert draft is not None
        return draft

    # ----- escritas externas — SÓ via executores do portão (src/executors.py) -----

    def send_draft(self, draft_id: str) -> None:
        self._request("POST", f"/users/{self._mailbox}/messages/{draft_id}/send")

    def move_to_deleted(self, message_id: str) -> dict[str, Any] | None:
        """Exclusão reversível: move para a pasta Itens Excluídos (nunca hard delete)."""
        return self._request(
            "POST",
            f"/users/{self._mailbox}/messages/{message_id}/move",
            json={"destinationId": "deleteditems"},
        )

    # ----- OneDrive (escrita permitida ao proposal_agent — auditada) -----

    def upload_file(self, remote_path: str, content: bytes) -> dict[str, Any]:
        """Upload simples (< 4 MB) no OneDrive da caixa comercial.

        remote_path relativo à raiz, ex.: "Propostas/Proposta_X.pptx".
        Retorna o driveItem (com webUrl).
        """
        response = self._http.put(
            f"{GRAPH_BASE}/users/{self._mailbox}/drive/root:/{remote_path}:/content",
            content=content,
            headers={
                "Authorization": f"Bearer {self._token_provider()}",
                "Content-Type": "application/octet-stream",
            },
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except ValueError:
                detail = response.text
            raise GraphError(f"Graph HTTP {response.status_code}: {detail}")
        return response.json()
