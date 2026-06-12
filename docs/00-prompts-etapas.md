# Sequência de prompts por etapa (colar no Claude Code, um por etapa)

**Etapa 0 — Conceito**
> Leia o CLAUDE.md. Atuando como o time descrito (dev full-stack + engenheiro de automação/instrumentação + consultor de vendas), escreva `docs/01-conceito.md`: visão da aplicação, personas (vendedor, SDR, gerente), jornadas de uso, casos de uso priorizados e o que fica fora do escopo da v1. Não escreva código ainda.

**Etapa 1 — Arquitetura**
> Leia o CLAUDE.md e o docs/01-conceito.md. Como arquiteto da solução, escreva `docs/02-arquitetura.md` com: diagrama de componentes (Mermaid), modelo de dados (tabelas e relações), contratos REST da API v1 (rotas, payloads), fluxo do portão de aprovação, e estratégia de autenticação do frontend. Liste riscos técnicos e decisões com justificativa.

**Etapa 2 — Fundação backend**
> Leia o CLAUDE.md e docs/02-arquitetura.md. Implemente o scaffold do backend: FastAPI, SQLAlchemy com SQLite, modelos `audit_log` e `approvals`, connector Omie em modo leitura, connector ms365 em modo leitura, `agents/base.py` (loop de tool use cru com retries e erros voltando como tool result), `monitor_agent` e o flow agendado de alerta de atraso. Inclua pytest com as APIs externas mockadas e um README de como rodar em venv. Não implemente as etapas seguintes.

**Etapa 3 — Email**
> Leia o CLAUDE.md. Implemente o `email_agent`: triagem da inbox (classificação), rascunho de resposta e de encaminhamento. Enviar exige registro em `approvals`; deletar é proibido sem aprovação. Exponha endpoints REST para o frontend listar emails triados, ver rascunhos e aprovar/rejeitar ações. Testes incluídos.

**Etapa 4 — Propostas**
> Leia o CLAUDE.md. Implemente o `proposal_agent` e o connector `pptx_2solve`: a partir de dados do cliente no Omie + inputs recebidos pela API (escopo, itens, prazo), gerar a proposta em PPTX no padrão 2Solve e salvar no OneDrive. Endpoints para o frontend alimentar os dados e baixar o resultado. Testes incluídos.

**Etapas 5–7** seguem o mesmo formato (escrita no CRM via approvals → engenharia → dashboards + advisor).

**Prompt de correção de bugs (usar sempre que algo quebrar)**
> Bug: [descreva o comportamento]. Primeiro escreva um teste que reproduz o bug e falha. Depois corrija o código até o teste passar, sem quebrar os demais testes. Explique a causa raiz em 3 linhas e registre no CHANGELOG.md.
