# 01 — Conceito: Assistente Comercial 2Solve

> Etapa 0 do plano de desenvolvimento. Documento de visão — sem código.
> Escrito sob as três lentes do projeto: desenvolvimento full-stack,
> engenharia de automação/instrumentação e consultoria de vendas B2B industrial.

## 1. Visão

A 2Solve vende projetos de automação e instrumentação industrial (adequação,
engenharia reversa, P&ID, malhas de controle, listas de instrumentos). O ciclo
comercial é longo, técnico e de alto valor: cada oportunidade exige follow-up
disciplinado, proposta técnica-comercial bem montada e comunicação consistente
com o cliente. Hoje esse trabalho é manual e disperso entre Omie (CRM/ERP),
Outlook e PowerPoint.

O **Assistente Comercial 2Solve** é uma aplicação web que centraliza e
automatiza esse fluxo:

- **Vigia** o pipeline no Omie e o calendário, e avisa antes que oportunidades
  esfriem (follow-up vencido, proposta parada, tarefa atrasada).
- **Tria** a caixa de entrada comercial, classifica emails e rascunha respostas
  e encaminhamentos — o humano só revisa e aprova.
- **Monta** propostas e apresentações no padrão visual 2Solve a partir dos
  dados do Omie + inputs do vendedor, incluindo conteúdo técnico de engenharia
  (fluxogramas, listas de instrumentos, memoriais).
- **Aconselha** o time: analisa o pipeline e sugere prioridades e próximos
  passos como um consultor de vendas.

Princípio central: **a IA propõe, o humano dispõe**. Nenhuma escrita externa
(email enviado, registro alterado no Omie) acontece sem passar pelo portão de
aprovação — com liberação gradual, ação por ação, conforme a confiança cresce.

### O que muda no dia a dia (proposta de valor)

| Hoje | Com o assistente |
|---|---|
| Follow-up depende da memória do vendedor | Alerta automático de atraso com contexto e sugestão de ação |
| Triagem de inbox consome o início do dia | Inbox já classificada, com rascunhos prontos para revisar |
| Proposta = copiar/colar PPTX antigo e ajustar | PPTX padrão 2Solve gerado a partir do Omie + formulário, em minutos |
| Conteúdo técnico refeito a cada proposta | Diagramas, TAGs e listas gerados a partir de templates de engenharia |
| Gerente cobra status em reunião | Dashboard com pipeline, atrasos e fila de aprovações em tempo real |

## 2. Personas

### P1 — Vendedor (executivo de contas)
Engenheiro de formação, carteira própria de clientes industriais. Passa o dia
entre visitas, emails e Omie. **Dores:** esquece follow-ups em semanas cheias;
perde tempo montando proposta; inbox lotada mistura cliente quente com spam.
**O que precisa:** alertas acionáveis ("a proposta da Usina X está parada há
9 dias — rascunho de follow-up pronto"), proposta gerada rápido, rascunhos de
email no seu tom.

### P2 — SDR / Pré-vendas
Qualifica leads que chegam por email/site/indicação e alimenta o Omie.
**Dores:** cadastrar lead no Omie é repetitivo; classificar o que é lead real
vs. fornecedor vs. spam toma tempo; não tem visão do que aconteceu com os
leads que passou adiante. **O que precisa:** triagem automática da inbox com
classificação (lead novo / cliente ativo / fornecedor / irrelevante), cadastro
no Omie pré-preenchido para aprovar, rastreio do lead no funil.

### P3 — Gerente comercial
Responsável pela meta. Vive de planilha exportada do Omie e cobrança em
reunião. **Dores:** não vê o funil em tempo real; descobre oportunidade
esfriada tarde demais; não sabe o que o time (nem o assistente) fez na semana.
**O que precisa:** dashboard de pipeline por estágio, lista de atrasos, taxa
de conversão e ticket médio; fila de aprovações para liberar ações do agente;
log de auditoria navegável.

## 3. Jornadas de uso

### J1 — Manhã do vendedor (monitor + email)
1. O `monitor_agent` rodou de madrugada (APScheduler): varreu Omie e calendário,
   achou 3 follow-ups vencidos e 1 proposta sem resposta há 10 dias.
2. O vendedor abre o dashboard: vê os alertas priorizados, cada um com contexto
   (cliente, valor, último contato) e sugestão de próximo passo.
3. O `email_agent` já triou a inbox: 2 emails de cliente quente no topo, com
   rascunho de resposta pronto. O vendedor edita uma frase, **aprova** — o
   email sai e a ação fica registrada em `audit_log`.

### J2 — Proposta em uma tarde (proposal + engineering)
1. Cliente pede proposta de adequação de instrumentação. O vendedor abre a
   tela "Nova proposta", seleciona o cliente (dados puxados do Omie) e
   preenche escopo, itens, prazo e condições.
2. O `engineering_agent` gera o conteúdo técnico: fluxograma do processo
   (Mermaid → imagem), lista preliminar de instrumentos com TAGs ISA-5.1 e
   memorial descritivo do escopo.
3. O `proposal_agent` monta o PPTX no padrão 2Solve com dados comerciais +
   conteúdo técnico e salva no OneDrive. O vendedor baixa, revisa e envia
   (envio por email também via aprovação).

### J3 — Lead novo sem fricção (email + crm)
1. Chega email de contato novo pedindo orçamento. O `email_agent` classifica
   como **lead novo** e extrai nome, empresa e contexto.
2. O `crm_agent` prepara o cadastro do cliente/oportunidade no Omie e o coloca
   na fila de aprovações.
3. O SDR revisa o cadastro pré-preenchido na tela de aprovações, corrige o que
   for preciso e aprova — só então o registro é criado no Omie.

### J4 — Sexta-feira do gerente (dashboard + advisor)
1. O gerente abre o dashboard: pipeline por estágio, oportunidades atrasadas,
   propostas geradas na semana, fila de aprovações pendentes.
2. O `advisor_agent` apresenta a análise da semana: "3 oportunidades acima de
   R$ 100 mil sem movimento há 14+ dias; o estágio 'proposta enviada' está
   acumulando — sugiro mutirão de follow-up; lead Y tem perfil de fechamento
   rápido, priorizar."
3. O gerente revisa o log de auditoria do assistente: o que foi feito, o que
   foi aprovado, o que foi rejeitado e por quem.

## 4. Casos de uso priorizados (ordem de entrega)

| # | Caso de uso | Agente | Etapa | Risco |
|---|---|---|---|---|
| UC1 | Alerta de oportunidade/tarefa atrasada (leitura Omie + calendário, notificação) | monitor | 2 | Zero (só leitura) |
| UC2 | Triagem e classificação da inbox comercial | email | 3 | Baixo (só leitura + rascunho) |
| UC3 | Rascunho de resposta/encaminhamento com aprovação para envio | email | 3 | Médio (escrita gated) |
| UC4 | Geração de proposta PPTX padrão 2Solve a partir de Omie + formulário | proposal | 4 | Baixo (gera arquivo) |
| UC5 | Cadastro/atualização de cliente e oportunidade no Omie via aprovação | crm | 5 | Médio (escrita gated) |
| UC6 | Conteúdo técnico de engenharia para propostas (fluxograma, lista de instrumentos, memorial) | engineering | 6 | Baixo |
| UC7 | Dashboard comercial completo + análise/recomendações de pipeline | advisor | 7 | Zero (só leitura) |

A ordem maximiza valor com risco controlado: começa com leitura pura (UC1),
prova o portão de aprovação no caso mais frequente (email), e só então libera
escrita no CRM.

## 5. Fora do escopo da v1

- **Voz** — transcrição de áudio/reunião → tarefa no Omie + rascunho de email
  (backlog pós-v1, já previsto no CLAUDE.md).
- **ML/DL próprio** — sem volume de dados rotulados ainda; scoring de leads com
  scikit-learn fica para quando houver histórico acumulado no banco.
- **Envio automático sem aprovação** — toda escrita externa nasce gated; a
  liberação por flag, ação por ação, é evolução operacional, não recurso da v1.
- **App mobile / notificações push** — v1 é web; notificação chega por email.
- **Faturamento/financeiro do Omie** — escopo é comercial (clientes,
  oportunidades, tarefas); módulos financeiros do ERP ficam de fora.
- **Multi-tenant** — a aplicação serve só a 2Solve; sem isolamento por
  organização.
- **Edição de PPTX no navegador** — o frontend alimenta dados e baixa o
  arquivo; edição fina é feita no PowerPoint.

## 6. Premissas e dependências

- Credenciais Omie (`app_key`/`app_secret`) com acesso aos módulos de CRM
  (clientes, oportunidades, tarefas/atividades).
- App registrado no Azure AD com escopos mínimos do Microsoft Graph
  (Mail.Read, Mail.ReadWrite para rascunhos, Mail.Send gated, Calendars.Read,
  Files.ReadWrite para a pasta de propostas).
- Chave da API Anthropic.
- Template PPTX oficial 2Solve disponível para o connector `pptx_2solve`.
- Um desenvolvedor frontend dedicado consumirá a API REST — o backend é o
  contrato (OpenAPI versionado).
