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

## Estado atual (Etapa 3)

- Connector Omie **somente leitura** (clientes, oportunidades, tarefas).
- Connector Graph: leitura de mail/calendário + rascunhos (Drafts); envio e
  exclusão só pelos executores do portão (`src/executors.py`).
- `monitor_agent`: varredura de atrasos → tabela `alerts` (cron diário 6h).
- `email_agent`: triagem da inbox → `emails_triaged`, rascunho de resposta/
  encaminhamento no Outlook (cron diário 7h). O agente NÃO tem ferramenta de
  envio nem exclusão direta — `solicitar_envio`/`solicitar_exclusao` só
  enfileiram em `approvals`; exclusão aprovada move para Itens Excluídos
  (reversível), nunca hard delete.
- Endpoints: `/emails/triaged`, `/emails/{id}/draft`,
  `/agents/email/triage`, além de alerts/approvals/runs da Etapa 2.
- Toda chamada de ferramenta de agente é auditada em `audit_log`.
