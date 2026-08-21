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


type JsonDict = dict[str, object]


class ToolError(Exception):
    """Tool failure reported to the MCP client as an `isError` result."""


class InvalidArgumentsError(ToolError):
    """Arguments failed the tool's input-model validation."""


class UnknownToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolCall[InputT: BaseModel]:
    services: ServicesProtocol
    actor: ActorContext
    data: InputT


def redact_keys(value: object, keys: frozenset[str]) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if key in keys else redact_keys(item, keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_keys(item, keys) for item in value]
    return value


class ToolProtocol(Protocol):
    name: str
    description: str
    scope: ToolScope

    def input_schema(self) -> JsonDict: ...
    @classmethod
    def audit_arguments(cls, arguments: JsonDict) -> object: ...
    def run(
        self, *, services: ServicesProtocol, actor: ActorContext, arguments: JsonDict
    ) -> str: ...


class Tool[InputT: BaseModel](ToolProtocol, ABC):
    input_model: type[InputT]
    # Argument keys carrying personal data, redacted before the audit line.
    audit_redacted_keys: frozenset[str] = frozenset()

    def input_schema(self) -> JsonDict:
        return self.input_model.model_json_schema()

    @classmethod
    def audit_arguments(cls, arguments: JsonDict) -> object:
        return redact_keys(arguments, cls.audit_redacted_keys)

    def run(
        self, *, services: ServicesProtocol, actor: ActorContext, arguments: JsonDict
    ) -> str:
        try:
            data = self.input_model.model_validate(arguments)
        except ValidationError as error:
            # Built from structured error fields, not str(error): the raw
            # pydantic text echoes input values and must not reach clients.
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: "
                f"{item['msg']}"
                for item in error.errors()
            )
            message = f"Invalid arguments: {details}"
            raise InvalidArgumentsError(message) from error
        return self.handle(ToolCall(services=services, actor=actor, data=data))

    @staticmethod
    @abstractmethod
    def handle(call: ToolCall[InputT]) -> str: ...


class ToolRegistry:
    def __init__(self, tools: Sequence[ToolProtocol]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def describe(self) -> list[JsonDict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]

    def audit_arguments(self, name: str, arguments: JsonDict) -> object:
        if (tool := self._tools.get(name)) is None:
            return "[redacted]"
        return tool.audit_arguments(arguments)

    def call(
        self,
        *,
        services: ServicesProtocol,
        actor: ActorContext,
        name: str,
        arguments: JsonDict,
    ) -> str:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name].run(
            services=services, actor=actor, arguments=arguments
        )
