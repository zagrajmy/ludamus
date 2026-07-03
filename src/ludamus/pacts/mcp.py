"""MCP gate contracts: caller identity and tool tiers."""

from dataclasses import dataclass
from enum import StrEnum


class ToolScope(StrEnum):
    MAINTAINER = "maintainer"
    ORGANIZER = "organizer"


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: int
    scope: ToolScope
    sphere_id: int | None = None
