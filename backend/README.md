# Backend — Assistente Comercial 2Solve

FastAPI + SQLAlchemy (SQLite) + agentes Anthropic com tool use cru.
Sem Docker: roda em `venv` direto na máquina/servidor.

## Rodar em desenvolvimento

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/mac: source .venv/bin/activate
pip install -e ".[dev]"

copy .env.example .env               # preencha as chaves (NUNCA commitar o .env)

uvicorn src.main:app --reload --port 8000
```

- API: http://localhost:8000/api/v1
- OpenAPI (contrato para o frontend): http://localhost:8000/docs
- O banco SQLite (`assistente.db`) é criado automaticamente no primeiro boot.

## Testes e qualidade

```powershell
pytest            # suíte completa (APIs externas mockadas — roda offline)
ruff check src ..\tests
mypy src
```

## Scheduler

Com `SCHEDULER_ENABLED=true` no `.env`, o APScheduler sobe junto com a API e
roda a varredura de atrasos do `monitor_agent` diariamente às
`MONITOR_CRON_HOUR` (padrão 6h, fuso America/Sao_Paulo). Disparo manual:
`POST /api/v1/agents/monitor/run`.

## Manter vivo em produção (sem Docker)

**Windows (nssm):**

```powershell
nssm install Assistente2Solve "C:\caminho\backend\.venv\Scripts\uvicorn.exe" "src.main:app --host 0.0.0.0 --port 8000"
nssm set Assistente2Solve AppDirectory "C:\caminho\backend"
nssm start Assistente2Solve
```

**Linux (systemd)** — `/etc/systemd/system/assistente2solve.service`:

```ini
[Unit]
Description=Assistente Comercial 2Solve
After=network.target

[Service]
WorkingDirectory=/opt/assistente/backend
ExecStart=/opt/assistente/backend/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
EnvironmentFile=/opt/assistente/backend/.env

[Install]
WantedBy=multi-user.target
```

## Propostas (Etapa 4)

`POST /api/v1/proposals` recebe os inputs do frontend (cliente, projeto,
escopo, itens com valores, prazo, condições) e dispara o `proposal_agent`
(modelo `CLAUDE_MODEL_PROPOSAL`): consulta o cliente no Omie, redige o
conteúdo, gera o PPTX no padrão visual 2Solve (`connectors/pptx_2solve.py`,
identidade extraída de `templates/Petroreconcavo_Carnauba_rev00.pptx`) e
publica no OneDrive (`ONEDRIVE_PROPOSALS_FOLDER`). Download local:
`GET /api/v1/proposals/{id}/download`. Regra: itens e valores saem exatamente
como informados — item sem valor vira "sob consulta", nunca preço inventado.

## Dashboards e advisor (Etapa 7 — fecha a v1)

- `GET /api/v1/dashboard/pipeline` — pipeline comercial por estágio (valor,
  quantidade, ticket médio), lido do `pipeline_cache` local.
- `GET /api/v1/dashboard/operations` — métricas do assistente (emails triados,
  fila de aprovações, executadas vs. rejeitadas, propostas, alertas, runs).
- `POST /api/v1/dashboard/sync` — sincroniza o `pipeline_cache` a partir do
  Omie (também roda no agendador, diário). O dashboard nunca consulta o Omie
  ao vivo (resiliência — risco R1).
- `POST /api/v1/agents/advisor/run` + `GET /api/v1/advisor/analysis` — o
  `advisor_agent` lê os resumos e os alertas abertos e registra uma análise do
  pipeline com recomendações priorizadas. **Dois tiers de modelo por custo:** o
  loop que orquestra a coleta roda no modelo rotineiro (Sonnet) e a síntese
  estratégica roda uma única vez no modelo pesado (Opus), com os números lidos
  do banco (sem alucinação).

As funções de agregação (`src/dashboard.py`) leem só o banco local — rodam
offline e são testadas sem credenciais.

## Engenharia (Etapa 6)

`POST /api/v1/agents/engineering/run` recebe uma demanda livre (opcionalmente
`proposal_id`) e dispara o `engineering_agent` (engenheiro de automação e
instrumentação): valida TAGs ISA-5.1, monta listas de instrumentos, gera
fluxogramas de processo em Mermaid e memoriais. A lógica fica em funções puras
testáveis (`connectors/engineering.py`); os artefatos são gravados em
`engineering_artifacts` (escrita LOCAL auditada, sem portão — não toca sistema
externo). Consulta: `GET /engineering/artifacts` (filtro por `kind` e
`proposal_id`) e `GET /engineering/artifacts/{id}`. Artefatos vinculados a uma
proposta podem alimentar o `proposal_agent`.

## Escrita no CRM (Etapa 5)

`POST /api/v1/agents/crm/run` recebe uma demanda livre (ex.: "cadastre o
cliente X com CNPJ ...", "mova a oportunidade 555 para a etapa 3") e dispara o
`crm_agent`: consulta clientes/oportunidades/etapas no Omie (leitura livre),
checa duplicidade por CNPJ antes de propor cadastro, e **enfileira** toda
criação/atualização em `approvals` (`omie_create` / `omie_update`). O agente
NÃO tem ferramenta de escrita direta nem de exclusão. A escrita só acontece
quando alguém aprova na fila (`/approvals`) — o executor (`src/executors.py`)
grava no Omie exatamente o payload congelado. Liberação gradual por
`action_flags` (deleção nunca auto-executa).

## Estado atual (Etapa 3)

- Connector Omie: leitura livre (clientes, oportunidades, tarefas, etapas) +
  escrita (criar/atualizar cliente e oportunidade) **só via executores**.
- Connector Graph: leitura de mail/calendário + rascunhos (Drafts); envio e
  exclusão só pelos executores do portão (`src/executors.py`).
- `monitor_agent`: varredura de atrasos → tabela `alerts` (cron diário 6h).
- `email_agent`: triagem da inbox → `emails_triaged`, rascunho de resposta/
  encaminhamento no Outlook (cron diário 7h). O agente NÃO tem ferramenta de
  envio nem exclusão direta — `solicitar_envio`/`solicitar_exclusao` só
  enfileiram em `approvals`; exclusão aprovada move para Itens Excluídos
  (reversível), nunca hard delete. **Dois tiers de modelo:** o loop de triagem
  (listar/ler/classificar) roda no modelo rotineiro (Sonnet); a redação da
  resposta ao cliente é feita pelo modelo de escrita cuidada (Opus) numa
  chamada encapsulada em `rascunhar_resposta`.
- Endpoints: `/emails/triaged`, `/emails/{id}/draft`,
  `/agents/email/triage`, além de alerts/approvals/runs da Etapa 2.
- Toda chamada de ferramenta de agente é auditada em `audit_log`.
