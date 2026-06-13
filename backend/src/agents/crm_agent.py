"""crm_agent — consulta e propõe cadastro/atualização no Omie (UC5).

Permissões (CLAUDE.md, tabela de agentes):
- Consultar (listar, buscar por CNPJ, etapas do funil): direto no Omie.
- Criar/atualizar cliente ou oportunidade: a ferramenta só ENFILEIRA em
  `approvals` (omie_create / omie_update). Nada é gravado no Omie sem
  aprovação humana. O agente NÃO tem ferramenta de escrita direta nem de
  exclusão (regras duras 1 e 2).
"""

from __future__ import annotations

import re
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.agents.base import BaseAgent, Tool
from src.approvals import request_approval
from src.connectors.omie import OmieClient

SYSTEM_PROMPT = """Você é o agente de CRM do time comercial da 2Solve (automação e \
instrumentação industrial). Você consulta e mantém os cadastros de clientes e \
oportunidades no Omie, atuando como um analista comercial cuidadoso.

Princípios:
1. ANTES de propor um cadastro de cliente, busque pelo CNPJ/CPF com
   buscar_cliente_por_cnpj para evitar duplicidade. Se já existir, proponha
   ATUALIZAÇÃO em vez de novo cadastro.
2. Para mover uma oportunidade de etapa, consulte listar_etapas_funil e use o
   código de etapa correto — nunca invente código de etapa.
3. Use APENAS os dados fornecidos na demanda ou retornados pelo Omie. Nunca
   invente CNPJ, razão social, e-mail, valores ou datas. Se faltar um dado
   obrigatório, diga o que falta e não enfileire a ação.
4. Toda criação/atualização vira um PEDIDO DE APROVAÇÃO humana — você não
   escreve no Omie diretamente. Preencha o resumo da aprovação de forma clara
   para o aprovador decidir sem abrir o Omie.

Ao final, responda em português o que consultou e quais pedidos de aprovação \
deixou na fila."""


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


class CrmAgent(BaseAgent):
    name = "crm"
    system_prompt = SYSTEM_PROMPT

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        omie: OmieClient | None = None,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
    ) -> None:
        self._omie = omie or OmieClient()
        tools = [
            Tool(
                name="listar_clientes",
                description="Lista clientes cadastrados no Omie (paginado).",
                input_schema={
                    "type": "object",
                    "properties": {"pagina": {"type": "integer", "minimum": 1,
                                              "default": 1}},
                },
                handler=lambda pagina=1: self._omie.list_clients(page=pagina),
            ),
            Tool(
                name="buscar_cliente_por_cnpj",
                description="Busca um cliente pelo CNPJ/CPF (para evitar duplicidade "
                "antes de cadastrar).",
                input_schema={
                    "type": "object",
                    "properties": {"cnpj_cpf": {"type": "string"}},
                    "required": ["cnpj_cpf"],
                },
                handler=lambda cnpj_cpf: self._omie.find_client_by_document(cnpj_cpf),
            ),
            Tool(
                name="consultar_cliente",
                description="Consulta os dados completos de um cliente pelo código Omie.",
                input_schema={
                    "type": "object",
                    "properties": {"codigo_cliente_omie": {"type": "integer"}},
                    "required": ["codigo_cliente_omie"],
                },
                handler=lambda codigo_cliente_omie: self._omie.get_client(
                    codigo_cliente_omie
                ),
            ),
            Tool(
                name="listar_oportunidades",
                description="Lista oportunidades do CRM Omie (paginado).",
                input_schema={
                    "type": "object",
                    "properties": {"pagina": {"type": "integer", "minimum": 1,
                                              "default": 1}},
                },
                handler=lambda pagina=1: self._omie.list_opportunities(page=pagina),
            ),
            Tool(
                name="listar_etapas_funil",
                description="Lista as etapas do funil de vendas cadastradas no Omie.",
                input_schema={"type": "object", "properties": {}},
                handler=lambda: self._omie.list_opportunity_stages(),
            ),
            Tool(
                name="solicitar_cadastro_cliente",
                description="Enfileira o CADASTRO de um novo cliente no Omie para "
                "APROVAÇÃO HUMANA. Nada é gravado até alguém aprovar.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "razao_social": {"type": "string"},
                        "nome_fantasia": {"type": "string"},
                        "cnpj_cpf": {"type": "string"},
                        "email": {"type": "string"},
                        "telefone": {"type": "string"},
                        "cidade": {"type": "string"},
                        "estado": {"type": "string", "description": "UF, ex.: ES"},
                    },
                    "required": ["razao_social", "cnpj_cpf"],
                },
                handler=self._request_create_client,
                is_write=True,
            ),
            Tool(
                name="solicitar_atualizacao_cliente",
                description="Enfileira a ATUALIZAÇÃO de um cliente existente no Omie "
                "para APROVAÇÃO HUMANA. Informe só os campos a alterar.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "codigo_cliente_omie": {"type": "integer"},
                        "campos": {
                            "type": "object",
                            "description": "campos a atualizar (nomes do Omie), "
                            "ex.: {\"email\": \"x@y.com\", \"telefone1_numero\": \"...\"}",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["codigo_cliente_omie", "campos"],
                },
                handler=self._request_update_client,
                is_write=True,
            ),
            Tool(
                name="solicitar_cadastro_oportunidade",
                description="Enfileira o CADASTRO de uma nova oportunidade no Omie para "
                "APROVAÇÃO HUMANA.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "codigo_cliente_omie": {"type": "integer"},
                        "valor_estimado": {"type": "number"},
                        "codigo_etapa": {"type": "integer",
                                         "description": "código de etapa do funil (Omie)"},
                        "observacao": {"type": "string"},
                    },
                    "required": ["titulo", "codigo_cliente_omie"],
                },
                handler=self._request_create_opportunity,
                is_write=True,
            ),
            Tool(
                name="solicitar_atualizacao_oportunidade",
                description="Enfileira a ATUALIZAÇÃO de uma oportunidade no Omie para "
                "APROVAÇÃO HUMANA (ex.: mover de etapa, ajustar valor).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "codigo_oportunidade": {"type": "integer"},
                        "campos": {
                            "type": "object",
                            "description": "campos a atualizar (nomes do Omie)",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["codigo_oportunidade", "campos"],
                },
                handler=self._request_update_opportunity,
                is_write=True,
            ),
        ]
        super().__init__(session_factory, tools, client=client, model=model)

    # ----- enfileiramento no portão (nenhuma escrita direta) -----

    def _enqueue(self, action_type: str, payload: dict[str, Any], preview: str) -> dict[str, Any]:
        assert self.session is not None and self.run is not None
        approval = request_approval(
            self.session,
            action_type=action_type,
            payload=payload,
            preview_text=preview,
            run_id=self.run.id,
        )
        return {"approval_id": approval.id, "status": approval.status}

    def _request_create_client(
        self,
        razao_social: str,
        cnpj_cpf: str,
        nome_fantasia: str = "",
        email: str = "",
        telefone: str = "",
        cidade: str = "",
        estado: str = "",
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            # chave de integração exigida pelo Omie no IncluirCliente
            "codigo_cliente_integracao": f"2S-{_digits(cnpj_cpf)}",
            "razao_social": razao_social,
            "cnpj_cpf": cnpj_cpf,
        }
        if nome_fantasia:
            data["nome_fantasia"] = nome_fantasia
        if email:
            data["email"] = email
        if telefone:
            digits = _digits(telefone)
            data["telefone1_ddd"] = digits[:2]
            data["telefone1_numero"] = digits[2:]
        if cidade:
            data["cidade"] = cidade
        if estado:
            data["estado"] = estado
        preview = (
            f"Cadastrar cliente no Omie\n"
            f"Razão social: {razao_social}\nCNPJ/CPF: {cnpj_cpf}\n"
            f"{('Fantasia: ' + nome_fantasia + chr(10)) if nome_fantasia else ''}"
            f"{('E-mail: ' + email + chr(10)) if email else ''}"
            f"{('Local: ' + cidade + '/' + estado) if cidade or estado else ''}"
        )
        return self._enqueue("omie_create", {"entity": "client", "data": data}, preview)

    def _request_update_client(
        self, codigo_cliente_omie: int, campos: dict[str, Any]
    ) -> dict[str, Any]:
        data = {"codigo_cliente_omie": codigo_cliente_omie, **campos}
        alteracoes = ", ".join(f"{k}={v!r}" for k, v in campos.items())
        preview = (
            f"Atualizar cliente Omie #{codigo_cliente_omie}\nAlterações: {alteracoes}"
        )
        return self._enqueue("omie_update", {"entity": "client", "data": data}, preview)

    def _request_create_opportunity(
        self,
        titulo: str,
        codigo_cliente_omie: int,
        valor_estimado: float | None = None,
        codigo_etapa: int | None = None,
        observacao: str = "",
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "identificacao": {
                "cDesOp": titulo,
                "nCodClien": codigo_cliente_omie,
            }
        }
        if valor_estimado is not None:
            data["ticket"] = {"nValorOp": valor_estimado}
        if codigo_etapa is not None:
            data["fasesStatus"] = {"nCodFase": codigo_etapa}
        if observacao:
            data["observacoes"] = {"cObs": observacao}
        valor = f"R$ {valor_estimado:,.2f}" if valor_estimado is not None else "—"
        preview = (
            f"Cadastrar oportunidade no Omie\nTítulo: {titulo}\n"
            f"Cliente Omie #{codigo_cliente_omie}\nValor estimado: {valor}"
        )
        return self._enqueue(
            "omie_create", {"entity": "opportunity", "data": data}, preview
        )

    def _request_update_opportunity(
        self, codigo_oportunidade: int, campos: dict[str, Any]
    ) -> dict[str, Any]:
        data = {
            "identificacao": {"nCodOp": codigo_oportunidade},
            **campos,
        }
        alteracoes = ", ".join(f"{k}={v!r}" for k, v in campos.items())
        preview = (
            f"Atualizar oportunidade Omie #{codigo_oportunidade}\n"
            f"Alterações: {alteracoes}"
        )
        return self._enqueue(
            "omie_update", {"entity": "opportunity", "data": data}, preview
        )
