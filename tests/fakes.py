"""Fakes da API Anthropic para testar o loop de tool use sem rede."""

from __future__ import annotations

from typing import Any


class TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class ToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input


class _Usage:
    def __init__(self, input_tokens: int = 10, output_tokens: int = 5) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResponse:
    def __init__(self, content: list[Any], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage()


class _FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic: sem respostas roteirizadas restantes")
        return self._responses.pop(0)


class FakeAnthropic:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = _FakeMessages(responses)
