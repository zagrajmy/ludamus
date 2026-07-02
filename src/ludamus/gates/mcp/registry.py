"""MCP tool registry.

Tools are thin adapters over `ServicesProtocol`: validate a pydantic input,
call a service, return the resulting DTO(s) as JSON text. The registry is the
single source of truth for what an MCP client can see and call; transports
(the HTTP endpoint today) stay dumb.

Every tool carries a `ToolScope`, and an endpoint builds its registry from
only its tier's tools — the security boundary between tiers is filtering at
wiring time, not per-call policy checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.mcp import ActorContext, ToolScope
    from ludamus.pacts.services import ServicesProtocol


class ToolError(Exception):
    """Tool failure reported to the MCP client as an `isError` result."""


class UnknownToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolCall[InputT: BaseModel]:
    services: ServicesProtocol
    actor: ActorContext
    data: InputT


class ToolProtocol(Protocol):
    name: str
    description: str
    scope: ToolScope

    def input_schema(self) -> dict[str, object]: ...
    def run(
        self,
        *,
        services: ServicesProtocol,
        actor: ActorContext,
        arguments: dict[str, object],
    ) -> str: ...


class Tool[InputT: BaseModel](ToolProtocol, ABC):
    input_model: type[InputT]

    def input_schema(self) -> dict[str, object]:
        return self.input_model.model_json_schema()

    def run(
        self,
        *,
        services: ServicesProtocol,
        actor: ActorContext,
        arguments: dict[str, object],
    ) -> str:
        try:
            data = self.input_model.model_validate(arguments)
        except ValidationError as error:
            message = f"Invalid arguments: {error}"
            raise ToolError(message) from error
        return self.handle(ToolCall(services=services, actor=actor, data=data))

    @staticmethod
    @abstractmethod
    def handle(call: ToolCall[InputT]) -> str: ...


class ToolRegistry:
    def __init__(self, tools: Sequence[ToolProtocol]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]

    def call(
        self,
        *,
        services: ServicesProtocol,
        actor: ActorContext,
        name: str,
        arguments: dict[str, object],
    ) -> str:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name].run(
            services=services, actor=actor, arguments=arguments
        )
