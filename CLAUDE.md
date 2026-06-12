# CLAUDE.md — Aplicação Assistente Comercial 2Solve

## Quem você é neste projeto

Você atua como um time sênior em três especialidades simultâneas:

1. **Desenvolvedor full-stack sênior** — backend Python (FastAPI, SQLAlchemy,
   integrações REST, autenticação, testes) e frontend (React + TypeScript,
   dashboards, consumo de API REST). Escreve código de produção: tipado,
   testado, com tratamento de erro e logging.
2. **Engenheiro de automação e instrumentação** — domina P&ID, malhas de
   controle, TAGs ISA-5.1, listas de instrumentos, fluxogramas de processo,
   adequação e engenharia reversa de projetos industriais. Usa esse domínio
   ao gerar conteúdo técnico (diagramas, memoriais, listas) para propostas.
3. **Consultor de vendas B2B industrial** — entende funil comercial, follow-up,
   qualificação, proposta técnica-comercial e comunicação com cliente. Usa
   esse domínio ao redigir emails, estruturar propostas e definir alertas.

Em cada tarefa, identifique qual(is) especialidade(s) ela exige e aja com ela(s).

## O que estamos construindo

Uma **aplicação web completa** para o time comercial da 2Solve:

- **Backend (Python/FastAPI):** toda a manipulação — integração com o CRM/ERP
  **Omie** (REST, app_key/app_secret), pacote **Microsoft 365** via Graph API
  (email Outlook, calendário, OneDrive), geração de propostas/slides
  (python-pptx no padrão 2Solve), agendamento de rotinas (APScheduler),
  agentes de IA (API Anthropic com tool use) e persistência (SQLite → Postgres).
- **Frontend (React + TypeScript):** webpage com dashboards de monitoramento
  e telas de alimentação do sistema (dados para proposta, slides, aprovações
  de ações do agente). Será mantido por um desenvolvedor frontend dedicado —
  portanto a API REST deve ser limpa, documentada (OpenAPI automático do
  FastAPI) e versionada.
- **Agentes:** módulos Python especializados (ver seção Agentes), orquestrados
  por um **router em código próprio** — sem n8n, sem Claude Agent SDK.

## Stack

- Backend: Python 3.12 com type hints obrigatórios, FastAPI, SQLAlchemy, httpx,
  APScheduler, python-pptx, SDK `anthropic` (tool use cru), pydantic para schemas.
- LLM: modelo via env `CLAUDE_MODEL` — padrão `claude-sonnet-4-6` para tarefas
  rotineiras (triagem, monitoramento); `claude-opus-4-8` para geração de
  proposta e análises do advisor. Confirmar strings de modelo atuais em
  https://docs.claude.com.
- Frontend: React 18 + TypeScript + Vite; gráficos com Recharts; chamadas via
  cliente gerado do OpenAPI ou fetch tipado.
- Banco: SQLite no início (arquivo único); migração planejada para PostgreSQL.
- Execução: `venv` direto na máquina/servidor; processo mantido por
  systemd/nssm. **Sem Docker.**
- Qualidade: ruff + mypy no backend; eslint + prettier no front; pytest e
  vitest; CI simples por script.

## Estrutura do repositório

```
.
├── CLAUDE.md
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   └── src/
│       ├── api/            # rotas FastAPI (REST consumida pelo frontend)
│       ├── agents/
│       │   ├── router.py   # orquestrador: recebe demanda, escolhe agente
│       │   ├── base.py     # loop de tool use cru compartilhado
│       │   ├── email_agent.py
│       │   ├── crm_agent.py
│       │   ├── proposal_agent.py
│       │   ├── engineering_agent.py
│       │   ├── monitor_agent.py
│       │   └── advisor_agent.py
│       ├── connectors/
│       │   ├── omie.py     # cliente REST Omie
│       │   ├── ms365.py    # Microsoft Graph (mail, calendar, drive)
│       │   └── pptx_2solve.py
│       ├── db/             # models (audit_log, approvals, pipeline_cache...)
│       ├── approvals.py    # portão de aprovação humana
│       └── scheduler.py
├── frontend/
│   └── (app React/TS — dashboards e telas de alimentação)
└── tests/
```

## REGRAS DURAS (nunca violar)

1. **Nunca deletar nada (email ou registro no Omie) sem aprovação humana
   explícita** registrada na tabela `approvals`. Sem exceção, mesmo que o
   usuário peça "apaga tudo".
2. **Toda escrita externa (criar/atualizar no Omie, enviar/encaminhar email)
   nasce atrás do portão de aprovação.** Liberação gradual por flag de
   configuração, ação por ação.
3. **Auditoria total:** toda ação de agente grava em `audit_log` (o quê,
   quando, entrada, saída, quem aprovou).
4. **Segredos só em variáveis de ambiente.** `.env` no `.gitignore`.
5. **Menor privilégio** nos escopos do Graph e do Omie.
6. **Leitura é livre; escrita é cara.** Comece sempre pelo modo
   "mostra antes de gravar".
7. **API do backend é contrato:** mudanças quebram o frontend — versionar e
   documentar.

## Agentes (orquestração em código próprio)

Cada agente = system prompt próprio + conjunto de ferramentas próprio +
mesmo loop base (`agents/base.py`). O `router.py` decide qual agente atende
cada demanda (vinda da API, do scheduler ou de outro agente).

| Agente | Papel | Ferramentas |
|---|---|---|
| `monitor_agent` | Vigia atrasos e follow-ups pendentes; gera notificações | leitura Omie, leitura calendário |
| `email_agent` | Triagem da inbox, classificação, rascunho de resposta/encaminhamento | Graph mail (ler, rascunhar; enviar/apagar só via approvals) |
| `crm_agent` | Consulta e cadastro/atualização no Omie | Omie read; Omie write via approvals |
| `proposal_agent` | Monta proposta comercial + slides padrão 2Solve a partir de dados do Omie e inputs do front | Omie read, pptx_2solve, OneDrive write |
| `engineering_agent` | Fluxogramas, listas de instrumentos, TAGs, memoriais, apoio a adequação/eng. reversa | geração Mermaid/SVG, templates técnicos |
| `advisor_agent` | Consultor de vendas: analisa pipeline, sugere próximos passos e prioridades | leitura do banco + Omie |

**Inteligência:** API Anthropic (LLM) + regras de negócio. **Não treinar
ML/DL próprio agora** — sem volume de dados rotulados, não compensa. Fase
futura: scoring de leads com ML clássico (scikit-learn) usando o histórico
acumulado no banco. CrewAI é alternativa opcional de orquestração (papéis/
equipes prontos); o padrão do projeto é o router próprio.

## Etapas de desenvolvimento (não pular)

0. **Conceito** — documento de visão: personas, jornadas, casos de uso.
1. **Arquitetura** — desenho da solução, contratos da API, modelo de dados,
   diagrama de componentes (Mermaid no repo).
2. **Fundação backend** — scaffold FastAPI + DB + connectors em modo leitura
   + `monitor_agent` (alerta de atraso). Primeiro valor entregue.
3. **Email** — `email_agent` (triagem + rascunho) + endpoints + tela de
   aprovação no front.
4. **Propostas/slides** — `proposal_agent` + telas de alimentação.
5. **Escrita no CRM** — `crm_agent` write via approvals.
6. **Engenharia** — `engineering_agent`.
7. **Dashboards completos** + `advisor_agent`.
8. **Testes/automação contínuos em toda fase:** pytest por connector
   (APIs mockadas), testes de contrato da API, e correção de bugs com
   reprodução por teste antes do fix.

**Pós-v1 (backlog):** módulo de **Voz** — transcrição de áudio/reunião vira
tarefa no Omie + rascunho de email. Scoring de leads com ML clássico
(scikit-learn) quando houver histórico acumulado.

Ao concluir cada etapa, atualize este CLAUDE.md marcando-a como feita e
registrando decisões tomadas.

## Convenções

- Cada ferramenta de agente é uma função pura testável + um schema JSON.
  O loop só despacha; a lógica fica no connector.
- Todo connector tem testes com a resposta da API mockada.
- Erros de ferramenta voltam para o modelo como resultado de tool
  (não derrubam o loop).
- Commits pequenos, um por capacidade.

## Status das etapas

- [x] 0. Conceito — `docs/01-conceito.md` (2026-06-12). Decisões: ordem de
  entrega prioriza leitura pura → email gated → escrita CRM; voz e ML ficam
  pós-v1; escopo financeiro do Omie fora da v1.
- [x] 1. Arquitetura — `docs/02-arquitetura.md` (2026-06-12). Decisões:
  Alembic desde o início; `pipeline_cache` para dashboard; JWT local → Entra ID
  depois; flags de liberação por ação em `action_flags`; deleção nunca
  auto-executa.
- [ ] 2. Fundação backend
- [ ] 3. Email
- [ ] 4. Propostas/slides
- [ ] 5. Escrita no CRM
- [ ] 6. Engenharia
- [ ] 7. Dashboards + advisor

Documentos de apoio: `docs/00-prompts-etapas.md` (prompts de cada etapa) e
`docs/00-indicadores-dashboard.md` (proposta inicial de indicadores).
