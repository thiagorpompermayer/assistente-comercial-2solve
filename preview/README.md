# Preview visual — Assistente Comercial 2Solve (v2)

Simulação navegável das telas da **visão refinada (v2)**, na identidade visual
da 2Solve. Abra [`index.html`](index.html) no navegador (arquivo único, funciona
offline, sem instalar nada).

## O que mostra (v2)

- **Login Microsoft** — entrada pela conta corporativa (define o usuário e a
  conta que envia e-mails).
- **Dashboard** — pipeline, operação e tarefas da semana.
- **Propostas** com 3 subabas:
  - *Nova proposta* — formulário do cliente/oportunidade (→ Omie) + anexos
    (→ pasta padrão no SharePoint).
  - *Tarefas* — tarefas do Omie por dia / semana / cliente.
  - *Enviadas & histórico* — acompanhamento de propostas enviadas e timeline.
- **E-mails** — composição por tipo/etapa (agradecimento de reunião, solicitação
  de info, envio de proposta, follow-up), texto editável e **Enviar** (pela conta
  do usuário).
- **Aprovações** e **Advisor**.

Os dados seguem o formato que a API REST vai expor (ver
`docs/04-replanejamento-v2.md`), então serve de **especificação viva** para o
frontend React + TypeScript.

## O que NÃO é

- Não é o frontend de produção (será React + TS + Vite) — é só visualização.
- **Todos os dados são fictícios.** Botões não chamam o backend.
- **Engenharia** saiu deste preview — o módulo foi pausado para ser repensado.

> Status do projeto: **v1 construída (Etapas 0–7)**; **v2 em arquitetura**,
> implementação pausada para alinhamento com o time.
