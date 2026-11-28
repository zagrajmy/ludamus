from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ExternalToolDTO(BaseModel):
    name: str
    slug: str
    url: str
    frame_hosts: list[str]


class ExternalToolRepositoryProtocol(Protocol):
    @staticmethod
    def read_active(slug: str) -> ExternalToolDTO: ...


class ExternalToolServiceProtocol(Protocol):
    def read_active(self, slug: str) -> ExternalToolDTO: ...
