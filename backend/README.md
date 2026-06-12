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

## Estado atual (Etapa 2)

- Connectors **somente leitura**: Omie (clientes, oportunidades, tarefas) e
  Microsoft Graph (mail, calendário).
- `monitor_agent` com varredura de atrasos → tabela `alerts`.
- Portão de aprovação (`src/approvals.py`) pronto: toda escrita externa das
  próximas etapas nasce `pending`; deleção nunca auto-executa.
- Toda chamada de ferramenta de agente é auditada em `audit_log`.
