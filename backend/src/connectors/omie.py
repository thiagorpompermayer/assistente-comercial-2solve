"""Cliente REST do Omie — leitura livre + escrita via executores do portão.

Padrão Omie: POST em {base}/{endpoint}/ com corpo
{"call": ..., "app_key": ..., "app_secret": ..., "param": [{...}]}.
Erros de negócio voltam como 200 com "faultstring" no corpo.

Retries exponenciais para 429/5xx/erros de transporte (risco R1).

ATENÇÃO (regras duras 1 e 2): os métodos da seção "escritas" só podem ser
chamados pelos executores do portão de aprovação (src/executors.py) — nunca
diretamente por ferramenta de agente. O crm_agent apenas ENFILEIRA pedidos.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.config import get_settings


class OmieError(RuntimeError):
    pass


class OmieClient:
    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        base_url: str | None = None,
        http: httpx.Client | None = None,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 4.0),
    ) -> None:
        settings = get_settings()
        self._app_key = app_key or settings.omie_app_key
        self._app_secret = app_secret or settings.omie_app_secret
        self._base_url = (base_url or settings.omie_base_url).rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)
        self._retry_delays = retry_delays

    def _call(self, endpoint: str, call: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {
            "call": call,
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "param": [params],
        }
        url = f"{self._base_url}/{endpoint}/"
        last_error: str = ""

        for attempt in range(len(self._retry_delays) + 1):
            try:
                response = self._http.post(url, json=body)
            except httpx.TransportError as exc:
                last_error = f"erro de transporte: {exc}"
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                else:
                    data = response.json()
                    if isinstance(data, dict) and "faultstring" in data:
                        raise OmieError(
                            f"Omie {data.get('faultcode', '?')}: {data['faultstring']}"
                        )
                    response.raise_for_status()
                    return data

            if attempt < len(self._retry_delays):
                time.sleep(self._retry_delays[attempt])

        raise OmieError(f"Omie indisponível após retries ({call}): {last_error}")

    # ----- leituras -----

    def list_clients(self, page: int = 1, per_page: int = 50) -> dict[str, Any]:
        return self._call(
            "geral/clientes",
            "ListarClientes",
            {"pagina": page, "registros_por_pagina": per_page, "apenas_importado_api": "N"},
        )

    def list_opportunities(self, page: int = 1, per_page: int = 50) -> dict[str, Any]:
        return self._call(
            "crm/oportunidades",
            "ListarOportunidades",
            {"pagina": page, "registros_por_pagina": per_page},
        )

    def list_tasks(self, page: int = 1, per_page: int = 50) -> dict[str, Any]:
        return self._call(
            "crm/tarefas",
            "ListarTarefas",
            {"pagina": page, "registros_por_pagina": per_page},
        )

    def get_client(self, client_id: int) -> dict[str, Any]:
        return self._call(
            "geral/clientes",
            "ConsultarCliente",
            {"codigo_cliente_omie": client_id},
        )

    def find_client_by_document(self, cnpj_cpf: str) -> dict[str, Any]:
        """Busca um cliente pelo CNPJ/CPF (filtro do ListarClientes)."""
        return self._call(
            "geral/clientes",
            "ListarClientes",
            {
                "pagina": 1,
                "registros_por_pagina": 5,
                "clientesFiltro": {"cnpj_cpf": cnpj_cpf},
            },
        )

    def list_opportunity_stages(self) -> dict[str, Any]:
        """Etapas do funil cadastradas no Omie (para validar movimentação)."""
        return self._call("crm/oportunidades-etapas", "ListarEtapas", {})

    # ----- escritas — SÓ via executores do portão (src/executors.py) -----

    def create_client(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._call("geral/clientes", "IncluirCliente", data)

    def update_client(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._call("geral/clientes", "AlterarCliente", data)

    def create_opportunity(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._call("crm/oportunidades", "IncluirOportunidade", data)

    def update_opportunity(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._call("crm/oportunidades", "AlterarOportunidade", data)
