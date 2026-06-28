"""Multiverse subdomain DTOs and protocols.

Sphere-scoped concerns. First bounded context: Panel (sphere-scoped
backoffice). Split per `plans/hex_refactor.md` if the file grows past
~12 top-level members or 1000 lines.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ludamus.pacts.legacy import EventDTO, EventListItemDTO, SiteDTO, SphereDTO


class DuplicateConnectionDisplayNameError(Exception):
    pass


class ConnectionInUseError(Exception):
    pass


class AnnouncementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    title: str
    content: str
    is_published: bool
    creation_time: datetime
    modification_time: datetime


class AnnouncementData(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(max_length=50000)
    is_published: bool


class AnnouncementsRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[AnnouncementDTO]: ...
    @staticmethod
    def list_published(sphere_id: int) -> list[AnnouncementDTO]: ...
    @staticmethod
    def get(sphere_id: int, pk: int) -> AnnouncementDTO: ...
    @staticmethod
    def create(sphere_id: int, data: AnnouncementData) -> AnnouncementDTO: ...
    @staticmethod
    def update(sphere_id: int, pk: int, *, data: AnnouncementData) -> AnnouncementDTO: ...
    @staticmethod
    def delete(sphere_id: int, pk: int) -> None: ...


class AnnouncementsServiceProtocol(Protocol):
    def list_for_sphere(self, sphere_id: int) -> list[AnnouncementDTO]: ...
    def list_published(self, sphere_id: int) -> list[AnnouncementDTO]: ...
    def get(self, sphere_id: int, pk: int) -> AnnouncementDTO: ...
    def create(self, sphere_id: int, data: AnnouncementData) -> AnnouncementDTO: ...
    def update(
        self, sphere_id: int, pk: int, data: AnnouncementData
    ) -> AnnouncementDTO: ...
    def delete(self, sphere_id: int, pk: int) -> None: ...


class ConnectionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    display_name: str
    has_secret: bool


class ConnectionsRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[ConnectionDTO]: ...
    @staticmethod
    def get(sphere_id: int, pk: int) -> ConnectionDTO: ...
    @staticmethod
    def create(sphere_id: int, display_name: str) -> ConnectionDTO: ...
    @staticmethod
    def update(sphere_id: int, pk: int, *, display_name: str) -> ConnectionDTO: ...
    @staticmethod
    def update_secret(sphere_id: int, pk: int, *, blob: bytes) -> None: ...
    @staticmethod
    def read_secret(sphere_id: int, pk: int) -> bytes: ...
    @staticmethod
    def delete(sphere_id: int, pk: int) -> None: ...


class EncryptorProtocol(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...


class DecryptorProtocol(Protocol):
    def decrypt(self, blob: bytes) -> bytes: ...


class ConnectionsServiceProtocol(Protocol):
    def list_for_sphere(self, sphere_id: int) -> list[ConnectionDTO]: ...
    def get(self, sphere_id: int, pk: int) -> ConnectionDTO: ...
    def create(
        self, sphere_id: int, display_name: str, secret_plaintext: bytes | None = None
    ) -> ConnectionDTO: ...
    def update(
        self,
        sphere_id: int,
        pk: int,
        display_name: str,
        secret_plaintext: bytes | None = None,
    ) -> ConnectionDTO: ...
    def delete(self, sphere_id: int, pk: int) -> None: ...


class EventsServiceProtocol(Protocol):
    def list_for_sphere(
        self, sphere_id: int, *, include_unpublished: bool
    ) -> list[EventListItemDTO]: ...
    def read_by_slug(self, sphere_id: int, slug: str) -> EventDTO: ...


class SpherePanelServiceProtocol(Protocol):
    def is_manager(self, sphere_id: int, user_slug: str) -> bool: ...
    def list_events(self, sphere_id: int) -> list[EventDTO]: ...
    def read(self, sphere_id: int) -> SphereDTO: ...
    def update_settings(
        self,
        sphere_id: int,
        *,
        allow_facilitator_session_edit: bool,
        logo: str | None = None,
    ) -> None: ...


class SitesServiceProtocol(Protocol):
    def read_site(self, sphere_id: int) -> SiteDTO: ...
