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
from typing import TYPE_CHECKING, ClassVar, Protocol

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


def json_schema[ModelT: BaseModel](model: type[ModelT]) -> JsonDict:
    return model.model_json_schema()


def validate_arguments[ModelT: BaseModel](
    model: type[ModelT], arguments: JsonDict
) -> ModelT:
    try:
        return model.model_validate(arguments)
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


class ToolProtocol(Protocol):
    name: str
    description: str
    scope: ToolScope

    def input_schema(self) -> JsonDict: ...
    def audit_arguments(self, arguments: JsonDict) -> JsonDict: ...
    def run(
        self, *, services: ServicesProtocol, actor: ActorContext, arguments: JsonDict
    ) -> str: ...


class OrganizerToolProtocol(ToolProtocol, Protocol):
    # What the maintainer endpoint needs to reopen an organizer tool with the
    # sphere and event passed as arguments instead of read off a token.
    @property
    def input_model(self) -> type[BaseModel]: ...
    @property
    def needs_event(self) -> bool: ...
    @property
    def maintainer_description(self) -> str | None: ...


class Tool[InputT: BaseModel](ToolProtocol, ABC):
    input_model: type[InputT]
    # Argument keys carrying personal data, redacted before the audit line.
    audit_redacted_keys: frozenset[str] = frozenset()
    # True when `handle` acts on the token's event (`token_event`). The
    # maintainer endpoint has no token event, so it asks for an `event_id`.
    needs_event: ClassVar[bool] = False
    # For the rare organizer description that is false for a maintainer.
    maintainer_description: ClassVar[str | None] = None

    def input_schema(self) -> JsonDict:
        return json_schema(self.input_model)

    def audit_arguments(self, arguments: JsonDict) -> JsonDict:
        keys = self.audit_redacted_keys
        return {
            name: "[redacted]" if name in keys else redact_keys(value, keys)
            for name, value in arguments.items()
        }

    def run(
        self, *, services: ServicesProtocol, actor: ActorContext, arguments: JsonDict
    ) -> str:
        data = validate_arguments(self.input_model, arguments)
        return self.handle(ToolCall(services=services, actor=actor, data=data))

    @staticmethod
    @abstractmethod
    def handle(call: ToolCall[InputT]) -> str: ...


class ToolRegistry:
    def __init__(self, tools: Sequence[ToolProtocol]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) < len(tools):
            # A second tool under one name would silently replace the first.
            names = [tool.name for tool in tools]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            message = f"Duplicate MCP tool names: {', '.join(duplicates)}"
            raise ValueError(message)

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
