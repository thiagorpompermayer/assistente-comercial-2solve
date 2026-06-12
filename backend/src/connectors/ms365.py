"""Microsoft Graph — SOMENTE LEITURA nesta fase (Etapa 2): mail e calendário.

Autenticação app-only (client credentials) via MSAL, escopo .default.
Menor privilégio: Mail.Read e Calendars.Read, restritos à caixa comercial
por Application Access Policy (ver docs/02-arquitetura.md §5).

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

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._http.get(
            f"{GRAPH_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._token_provider()}"},
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except ValueError:
                detail = response.text
            raise GraphError(f"Graph HTTP {response.status_code}: {detail}")
        return response.json()

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
