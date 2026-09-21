"""Multiverse subdomain business logic.

Sphere-scoped concerns. First feature: import-connections CRUD. Split per
`plans/hex_refactor.md` if the file grows past ~12 top-level members or
1000 lines.
"""

from typing import TYPE_CHECKING

from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.multiverse import SphereAccessDTO, SphereSettingsOutcome
from ludamus.specs.permissions import ROLE_CAPABILITIES

if TYPE_CHECKING:
    from ludamus.pacts.encounter import EncounterRepositoryProtocol
    from ludamus.pacts.images import UploadedFileProtocol
    from ludamus.pacts.legacy import (
        EventDTO,
        EventRepositoryProtocol,
        SphereDTO,
        SphereRepositoryProtocol,
        SphereUpdateData,
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
    """Read-side context loader for the multiverse sphere panel."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        spheres: SphereRepositoryProtocol,
        events: EventRepositoryProtocol,
        encounters: EncounterRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._spheres = spheres
        self._events = events
        self._encounters = encounters

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
        encounters_policy: EncountersPolicy,
        logo: UploadedFileProtocol | str | None = None,
        confirmed_encounters_disable: bool = False,
    ) -> SphereSettingsOutcome:
        """Save the sphere's settings, refusing an unconfirmed hide.

        Returns:
            NEEDS_CONFIRMATION when the save would turn encounters off while
            the sphere still has some — nothing is written, and the caller is
            expected to warn and ask again. SAVED otherwise.
        """
        data: SphereUpdateData = {
            "allow_facilitator_session_edit": allow_facilitator_session_edit,
            "encounters_policy": encounters_policy.value,
        }
        # None keeps the stored logo, "" removes it, a file replaces it.
        if logo is not None:
            data["logo"] = logo
        with self._transaction.atomic():
            if (
                not confirmed_encounters_disable
                and encounters_policy is EncountersPolicy.NONE
                and self._spheres.read(sphere_id).encounters_policy
                is not EncountersPolicy.NONE
                and self._encounters.exists_for_sphere(sphere_id)
            ):
                return SphereSettingsOutcome.NEEDS_CONFIRMATION
            self._spheres.update(sphere_id, data)
            return SphereSettingsOutcome.SAVED

    def update_logo(self, sphere_id: int, logo: UploadedFileProtocol | str) -> None:
        data: SphereUpdateData = {"logo": logo}
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
        self._read_cache: dict[int, SphereDTO] = {}

    def read(self, sphere_id: int) -> SphereDTO:
        # Memoised because the service is built per request and the current
        # sphere is read several times in one: the sites context processor,
        # the panel's access checks and the pages that render its name.
        if sphere_id not in self._read_cache:
            self._read_cache[sphere_id] = self._spheres.read(sphere_id)
        return self._read_cache[sphere_id]

    def list_spheres(self) -> list[SphereListItemDTO]:
        return self._directory.list_all()
