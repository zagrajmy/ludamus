"""Multiverse subdomain business logic.

Sphere-scoped concerns. First feature: import-connections CRUD. Split per
`plans/hex_refactor.md` if the file grows past ~12 top-level members or
1000 lines.
"""

from typing import TYPE_CHECKING

from ludamus.pacts.multiverse import SphereAccessDTO
from ludamus.specs.permissions import ROLE_CAPABILITIES

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        EventDTO,
        EventRepositoryProtocol,
        SphereDTO,
        SphereRepositoryProtocol,
        SphereUpdateData,
        UploadedFileProtocol,
    )
    from ludamus.pacts.multiverse import (
        AnnouncementData,
        AnnouncementDTO,
        AnnouncementsRepositoryProtocol,
        ConnectionDTO,
        ConnectionsRepositoryProtocol,
        EncryptorProtocol,
        SphereDirectoryRepositoryProtocol,
        SphereListItemDTO,
        SphereRole,
    )
    from ludamus.pacts.services import TransactionProtocol


class AnnouncementsService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        announcements: AnnouncementsRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._announcements = announcements

    def list_for_sphere(self, sphere_id: int) -> list[AnnouncementDTO]:
        return self._announcements.list_for_sphere(sphere_id)

    def list_published(self, sphere_id: int) -> list[AnnouncementDTO]:
        return self._announcements.list_published(sphere_id)

    def get(self, sphere_id: int, pk: int) -> AnnouncementDTO:
        return self._announcements.get(sphere_id, pk)

    def create(self, sphere_id: int, data: AnnouncementData) -> AnnouncementDTO:
        with self._transaction.atomic():
            return self._announcements.create(sphere_id, data)

    def update(
        self, sphere_id: int, pk: int, data: AnnouncementData
    ) -> AnnouncementDTO:
        with self._transaction.atomic():
            return self._announcements.update(sphere_id, pk, data)

    def delete(self, sphere_id: int, pk: int) -> None:
        with self._transaction.atomic():
            self._announcements.delete(sphere_id, pk)


class ConnectionsService:
    """CRUD + encrypted-secret lifecycle for sphere-scoped connections."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        connections: ConnectionsRepositoryProtocol,
        encryptor: EncryptorProtocol,
    ) -> None:
        self._transaction = transaction
        self._connections = connections
        self._encryptor = encryptor

    def list_for_sphere(self, sphere_id: int) -> list[ConnectionDTO]:
        return self._connections.list_for_sphere(sphere_id)

    def get(self, sphere_id: int, pk: int) -> ConnectionDTO:
        return self._connections.get(sphere_id, pk)

    def create(
        self, sphere_id: int, display_name: str, secret_plaintext: bytes | None = None
    ) -> ConnectionDTO:
        with self._transaction.atomic():
            connection = self._connections.create(sphere_id, display_name)
            if secret_plaintext is not None:
                blob = self._encryptor.encrypt(secret_plaintext)
                self._connections.update_secret(sphere_id, connection.pk, blob)
            return connection

    def update(
        self,
        sphere_id: int,
        pk: int,
        display_name: str,
        secret_plaintext: bytes | None = None,
    ) -> ConnectionDTO:
        with self._transaction.atomic():
            connection = self._connections.update(sphere_id, pk, display_name)
            if secret_plaintext is not None:
                blob = self._encryptor.encrypt(secret_plaintext)
                self._connections.update_secret(sphere_id, pk, blob)
            return connection

    def delete(self, sphere_id: int, pk: int) -> None:
        with self._transaction.atomic():
            self._connections.delete(sphere_id, pk)


class SpherePanelService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        spheres: SphereRepositoryProtocol,
        events: EventRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._spheres = spheres
        self._events = events

    def manager_role(self, sphere_id: int, user_slug: str) -> SphereRole | None:
        return self._spheres.manager_role(sphere_id, user_slug)

    def access(self, sphere_id: int, user_slug: str) -> SphereAccessDTO:
        role = self._spheres.manager_role(sphere_id, user_slug)
        return SphereAccessDTO(
            role=role, capabilities=ROLE_CAPABILITIES[role] if role else frozenset()
        )

    def list_events(self, sphere_id: int) -> list[EventDTO]:
        return self._events.list_by_sphere(sphere_id)

    def read(self, sphere_id: int) -> SphereDTO:
        return self._spheres.read(sphere_id)

    def update_settings(
        self,
        sphere_id: int,
        *,
        allow_facilitator_session_edit: bool,
        parley_enabled: bool,
        logo: UploadedFileProtocol | str | None = None,
    ) -> None:
        data: SphereUpdateData = {
            "allow_facilitator_session_edit": allow_facilitator_session_edit,
            "parley_enabled": parley_enabled,
        }
        # None keeps the stored logo, "" removes it, a file replaces it.
        if logo is not None:
            data["logo"] = logo
        with self._transaction.atomic():
            self._spheres.update(sphere_id, data)


class SitesService:
    def __init__(
        self,
        spheres: SphereRepositoryProtocol,
        directory: SphereDirectoryRepositoryProtocol,
    ) -> None:
        self._spheres = spheres
        self._directory = directory

    def read(self, sphere_id: int) -> SphereDTO:
        return self._spheres.read(sphere_id)

    def list_spheres(self) -> list[SphereListItemDTO]:
        return self._directory.list_all()
