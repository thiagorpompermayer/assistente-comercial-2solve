"""Loop de tool use cru compartilhado por todos os agentes.

Convenções do CLAUDE.md:
- Cada ferramenta = função pura testável + schema JSON; o loop só despacha.
- Erros de ferramenta voltam ao modelo como tool_result com is_error=True
  (não derrubam o loop).
- Toda chamada de ferramenta grava em audit_log (regra dura 3).
- Retries exponenciais nas chamadas à API Anthropic (429/5xx/conexão).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.db.models import AgentRun, AuditLog, utcnow

logger = logging.getLogger(__name__)

MAX_TURNS = 20
RETRY_DELAYS = (1.0, 3.0, 9.0)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    is_write: bool = False

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class AgentResult:
    run_id: int
    status: str  # done|error
    output_text: str


class BaseAgent:
    name: str = "base"
    system_prompt: str = ""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tools: list[Tool],
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        settings = get_settings()
        self._session_factory = session_factory
        self._tools = tools
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = model or settings.claude_model
        self._max_tokens = max_tokens
        # Sessão/run correntes, disponíveis aos handlers durante o run.
        self.session: Session | None = None
        self.run: AgentRun | None = None

    def run_demand(
        self, demand: str, trigger: str = "api", run_id: int | None = None
    ) -> AgentResult:
        with self._session_factory() as session:
            run = session.get(AgentRun, run_id) if run_id is not None else None
            if run is None:
                run = AgentRun(agent=self.name, trigger=trigger)
                session.add(run)
            run.status = "running"
            run.input_json = {"demand": demand}
            run.started_at = utcnow()
            session.commit()

            self.session, self.run = session, run
            try:
                text = self._loop(session, run, demand)
            except Exception as exc:  # noqa: BLE001 — registrar, nunca derrubar scheduler/API
                logger.exception("agente %s falhou (run %s)", self.name, run.id)
                run.status = "error"
                run.error = str(exc)
                text = ""
            else:
                run.status = "done"
                run.output_json = {"text": text}
            finally:
                run.finished_at = utcnow()
                session.commit()
                self.session = self.run = None

            return AgentResult(run_id=run.id, status=run.status, output_text=text)

    def _loop(self, session: Session, run: AgentRun, demand: str) -> str:
        messages: list[dict[str, Any]] = [{"role": "user", "content": demand}]

        for _turn in range(MAX_TURNS):
            response = self._create_message(messages)
            run.tokens_in += response.usage.input_tokens
            run.tokens_out += response.usage.output_tokens

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                return "".join(
                    block.text for block in response.content if block.type == "text"
                )

            messages.append({"role": "assistant", "content": response.content})
            results = [self._dispatch(session, run, block) for block in tool_uses]
            session.commit()  # audit_log persiste a cada turno, mesmo se o run falhar depois
            messages.append({"role": "user", "content": results})

        raise RuntimeError(f"limite de {MAX_TURNS} turnos atingido sem resposta final")

    def _dispatch(self, session: Session, run: AgentRun, block: Any) -> dict[str, Any]:
        tool = self._tools_by_name.get(block.name)
        tool_input: dict[str, Any] = block.input or {}
        try:
            if tool is None:
                raise LookupError(f"ferramenta desconhecida: {block.name}")
            output = tool.handler(**tool_input)
            is_error = False
        except Exception as exc:  # noqa: BLE001 — erro volta ao modelo como tool_result
            output = f"Erro na ferramenta {block.name}: {exc}"
            is_error = True

        content = output if isinstance(output, str) else json.dumps(
            output, ensure_ascii=False, default=str
        )
        session.add(
            AuditLog(
                run_id=run.id,
                tool_name=block.name,
                input_json=tool_input,
                output_json={"content": content[:10_000], "is_error": is_error},
                is_write=bool(tool and tool.is_write),
            )
        )
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
            "is_error": is_error,
        }

    def _create_message(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        system: str | None = None,
        tools: list[Tool] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        """Uma chamada à API Messages com retries. Os overrides permitem que um
        agente use modelos diferentes por etapa (ex.: Sonnet rotineiro x Opus
        para raciocínio pesado) reusando a mesma lógica de retry."""
        tool_defs = [t.to_anthropic() for t in (self._tools if tools is None else tools)]
        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "max_tokens": self._max_tokens,
            "system": self.system_prompt if system is None else system,
            "messages": messages,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        last_exc: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self._client.messages.create(**kwargs)
            except anthropic.APIConnectionError as exc:
                last_exc = exc
            except anthropic.APIStatusError as exc:
                if exc.status_code != 429 and exc.status_code < 500:
                    raise
                last_exc = exc
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
        raise RuntimeError(f"API Anthropic indisponível após retries: {last_exc}")
