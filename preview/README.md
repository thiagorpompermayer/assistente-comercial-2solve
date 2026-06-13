# Preview visual — Assistente Comercial 2Solve

Simulação navegável das telas da aplicação web, na identidade visual da 2Solve.
Abra [`index.html`](index.html) no navegador (arquivo único, funciona offline,
sem instalar nada).

## O que é

- Mockup de alta fidelidade das 6 telas: Dashboard, Aprovações, Emails triados,
  Propostas, Engenharia e Advisor.
- Os dados seguem o **formato exato que a API REST v1 devolve** (`/dashboard/pipeline`,
  `/approvals`, `/emails/triaged`, `/advisor/analysis`, etc.), então serve de
  **especificação viva** para o desenvolvimento do frontend React + TypeScript.

## O que NÃO é

- Não é o frontend de produção (esse será React + TS + Vite, mantido pelo dev
  frontend) — é só uma visualização.
- **Todos os dados são fictícios** (clientes, valores, emails são exemplos
  inventados). Nenhum dado real de cliente. Os botões Aprovar/Rejeitar alteram
  apenas a tela, não chamam o backend.
