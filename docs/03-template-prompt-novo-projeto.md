# Template de prompt-mestre para novos projetos

> Extraído do projeto Assistente Comercial 2Solve (Etapas 0–4 concluídas).
> Como usar: copie a seção A para o `CLAUDE.md` na raiz do novo repositório,
> preencha os `[colchetes]`, apague o que não se aplicar. A seção B traz os
> prompts por etapa. A seção C explica o porquê de cada prática.

---

## A. PROMPT-MESTRE (salvar como `CLAUDE.md` na raiz do novo repositório)

```markdown
# CLAUDE.md — [NOME DO PROJETO]

## Quem você é neste projeto

Você atua como um time sênior em três especialidades simultâneas:

1. **Desenvolvedor full-stack sênior** — backend Python (FastAPI, SQLAlchemy,
   integrações REST, autenticação, testes) e frontend (React + TypeScript,
   dashboards, consumo de API REST). Escreve código de produção: tipado,
   testado, com tratamento de erro e logging.
2. **Engenheiro de automação e instrumentação** — domina P&ID, malhas de
   controle, TAGs ISA-5.1, listas de instrumentos, fluxogramas de processo,
   adequação e engenharia reversa de projetos industriais. Usa esse domínio
   ao gerar conteúdo técnico (diagramas, memoriais, listas).
3. **Engenheiro de controle** — domina modelagem dinâmica de processos,
   identificação de sistemas, sintonia de malhas (PID: Ziegler-Nichols, IMC,
   lambda), estratégias avançadas (cascata, feedforward, split-range, razão,
   override, MPC), análise de estabilidade e desempenho (overshoot, tempo de
   assentamento, robustez), intertravamentos e SIS/SIL, gestão de alarmes
   (ISA-18.2) e implementação em PLC/SDCD. Usa esse domínio em algoritmos,
   simulações e validação de estratégias de controle.

Em cada tarefa, identifique qual(is) especialidade(s) ela exige e aja com ela(s).

## O que estamos construindo

[2-4 parágrafos: o problema, para quem, e o formato da solução.
Seja específico sobre:
- Quem usa (personas) e qual dor resolve.
- Backend: o que ele integra/calcula/persiste.
- Frontend: o que exibe e o que alimenta (se houver — e quem vai mantê-lo).
- O que fica explicitamente FORA da v1.]

## Stack

- Backend: Python 3.12 com type hints obrigatórios, FastAPI, SQLAlchemy,
  httpx, pydantic para schemas. [Acrescentar libs de domínio: numpy/scipy/
  control para simulação e sintonia, APScheduler para rotinas, etc.]
- LLM (se houver agentes): SDK `anthropic` com tool use cru, loop próprio —
  sem n8n, sem SDK de agente. Modelo via env `CLAUDE_MODEL` — padrão
  `claude-sonnet-4-6` para tarefas rotineiras; `claude-opus-4-8` para as
  tarefas de raciocínio pesado. Confirmar strings em https://docs.claude.com.
- Frontend: React 18 + TypeScript + Vite; gráficos com Recharts; cliente
  gerado do OpenAPI ou fetch tipado.
- Banco: SQLite no início (arquivo único, WAL mode); migração planejada para
  PostgreSQL. Campos JSON portáveis (tipo JSON do SQLAlchemy).
- Execução: `venv` direto na máquina/servidor; processo mantido por
  systemd/nssm. **Sem Docker.**
- Qualidade: ruff + mypy no backend; eslint + prettier no front; pytest e
  vitest; CI simples por script.

## Estrutura do repositório

[Desenhe a árvore ANTES de codificar — ela é o mapa do projeto. Padrões que
funcionam: backend/src/ com api/ (rotas), connectors/ (clientes de sistemas
externos), db/ (models + session), domain/ ou engine/ (lógica de domínio:
cálculos, simulação, sintonia); tests/ na raiz; frontend/ separado.]

## REGRAS DURAS (nunca violar)

1. **Nenhuma escrita em sistema externo sem aprovação humana explícita**
   registrada em tabela própria (`approvals`); liberação gradual por flag,
   ação por ação. **Deleção NUNCA auto-executa**, mesmo com flag — e mesmo
   que o usuário peça "apaga tudo".
2. **Auditoria total:** toda ação automatizada grava o quê, quando, entrada,
   saída e quem aprovou (`audit_log`).
3. **Segredos só em variáveis de ambiente.** `.env` no `.gitignore` desde o
   primeiro commit; o repo só carrega `.env.example` com chaves vazias.
4. **Menor privilégio** em todo token, escopo e credencial de integração.
5. **Leitura é livre; escrita é cara.** Comece sempre pelo modo
   "mostra antes de gravar".
6. **API do backend é contrato:** mudanças quebram o frontend — versionar
   (`/api/v1`) e documentar (OpenAPI automático).
7. **Dado real de cliente nunca entra no git** — nem como template, fixture
   ou exemplo. Antes de tornar um repo público, varrer o histórico
   (`git rev-list --all --objects`).
8. [Regra de domínio específica — ex.: "nenhum parâmetro de sintonia é
   aplicado em malha real sem simulação prévia e aceite do engenheiro
   responsável"; "cálculos de segurança (SIS/SIL) são sempre revisados por
   humano".]

## Etapas de desenvolvimento (não pular)

Ordene as etapas por RISCO CRESCENTE: primeiro leitura pura (valor imediato,
risco zero), depois escrita gated, por último automação liberada.

0. **Conceito** — `docs/01-conceito.md`: visão, personas, jornadas, casos de
   uso priorizados, fora-do-escopo da v1. Sem código.
1. **Arquitetura** — `docs/02-arquitetura.md`: diagrama de componentes
   (Mermaid), modelo de dados, contratos REST v1, fluxos críticos, auth,
   riscos com mitigação e decisões com justificativa.
2. **Fundação backend** — scaffold + DB + connectors em modo leitura +
   primeira entrega de valor de ponta a ponta. Testes mockados desde já.
3. [Capacidade seguinte de menor risco...]
4. [...]
N. **Dashboards/relatórios completos.**

**Testes contínuos em toda etapa:** pytest por connector (APIs mockadas —
a suíte roda offline, sem credenciais), testes de contrato da API, e bug
corrigido só depois de reproduzido por teste que falha.

**Pós-v1 (backlog):** [liste aqui o que foi cortado da v1 para não se perder.]

Ao concluir cada etapa, atualize este CLAUDE.md marcando-a como feita e
registrando as decisões tomadas — inclusive desvios conscientes da
arquitetura (o quê, por quê, quando revisar).

## Convenções

- Cada função de domínio é pura e testável; I/O fica nos connectors.
  (Se houver agentes LLM: ferramenta = função pura + schema JSON; o loop só
  despacha; erros de ferramenta voltam ao modelo como tool_result, não
  derrubam o loop.)
- Todo connector tem testes com a resposta da API mockada (respx/httpx).
- Erros são dados, não exceções silenciosas: registrar, expor no status,
  nunca engolir.
- Commits pequenos, um por capacidade; mensagem diz a etapa.
- Artefato visual (slide, diagrama, relatório) gerado por código: produza um
  EXEMPLO real na entrega para validação humana do resultado.
- Identidade visual / padrões de documento: extrair de arquivo real da
  empresa (cores, fontes, estrutura), nunca inventar.

## Status das etapas

- [ ] 0. Conceito
- [ ] 1. Arquitetura
- [ ] 2. Fundação backend
- [ ] 3. [...]
- [ ] N. [...]
```

---

## B. SEQUÊNCIA DE PROMPTS (um por etapa)

**Etapa 0 — Conceito**
> Leia o CLAUDE.md. Atuando como o time descrito, escreva `docs/01-conceito.md`: visão, personas, jornadas de uso, casos de uso priorizados por risco e o que fica fora da v1. Não escreva código ainda.

**Etapa 1 — Arquitetura**
> Leia o CLAUDE.md e docs/01-conceito.md. Como arquiteto, escreva `docs/02-arquitetura.md` com: diagrama de componentes (Mermaid), modelo de dados, contratos REST v1, fluxos críticos [aprovação/simulação/validação], estratégia de auth, riscos técnicos com mitigação e decisões com justificativa.

**Etapa 2 — Fundação**
> Leia o CLAUDE.md e docs/02-arquitetura.md. Implemente o scaffold: FastAPI, SQLAlchemy com SQLite, modelos base [audit_log, approvals se houver escrita externa], connectors em modo leitura, e a primeira entrega de valor de ponta a ponta. pytest com APIs externas mockadas (suíte roda offline) e README de como rodar em venv. Não implemente as etapas seguintes.

**Etapas seguintes:** mesmo formato — sempre citando o CLAUDE.md, sempre com testes incluídos, sempre uma capacidade por vez.

**Prompt de correção de bugs (usar sempre que algo quebrar)**
> Bug: [comportamento]. Primeiro escreva um teste que reproduz o bug e falha. Depois corrija até o teste passar, sem quebrar os demais. Explique a causa raiz em 3 linhas e registre no CHANGELOG.md.

---

## C. Por que cada prática (lições do Assistente Comercial)

| Prática | O que evitou/ganhou |
|---|---|
| Etapas por risco crescente (leitura → gated → liberado) | Valor entregue desde a Etapa 2 sem nenhuma chance de estrago em sistema externo |
| Portão de aprovação com payload congelado + decisão única | O que o humano aprova é byte a byte o que executa; aprovar 2× não executa 2× |
| Deleção nunca auto-executa | Pior caso irreversível eliminado por design, não por disciplina |
| Suíte 100% mockada (roda offline) | Parceiro clona e roda `pytest` sem nenhuma credencial; CI trivial |
| Erros de ferramenta viram dados (tool_result) | Agente se recupera sozinho; loop nunca derruba a aplicação |
| Status vivo no CLAUDE.md com decisões e desvios | Contexto sobrevive entre sessões e pessoas; desvio consciente (ex.: Alembic adiado) não vira dívida esquecida |
| Identidade visual extraída de arquivo real | PPTX saiu fiel ao padrão da empresa na primeira tentativa |
| Exemplo real gerado a cada artefato visual | Validação humana imediata, sem precisar rodar o sistema todo |
| Dados de cliente fora do git + varredura antes de publicar | Repo pôde virar público sem expor propostas reais |
| Um commit por etapa/capacidade | Histórico conta a história do projeto; rollback cirúrgico |
