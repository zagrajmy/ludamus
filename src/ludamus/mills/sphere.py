"""Multiverse subdomain business logic.

Sphere-scoped concerns. First feature: import-connections CRUD. Split per
`plans/hex_refactor.md` if the file grows past ~12 top-level members or
1000 lines.
"""

from typing import TYPE_CHECKING

from ludamus.pacts.encounter import EncountersPolicy
from ludamus.pacts.sphere import Capability, SphereSettingsOutcome
from ludamus.specs.parley import event_chat_on
from ludamus.specs.permissions import sphere_access

if TYPE_CHECKING:
    from ludamus.pacts.encounter import EncounterRepositoryProtocol
    from ludamus.pacts.event import EventDTO, EventRepositoryProtocol
    from ludamus.pacts.images import UploadedFileProtocol
    from ludamus.pacts.notifications import AnnouncementFanoutSchedulerProtocol
    from ludamus.pacts.parley import ParleyRevocationServiceProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sphere import (
        AnnouncementData,
        AnnouncementDTO,
        AnnouncementsRepositoryProtocol,
        ConnectionDTO,
        ConnectionsRepositoryProtocol,
        EncryptorProtocol,
        SphereAccessDTO,
        SphereChatSettings,
        SphereDirectoryRepositoryProtocol,
        SphereDTO,
        SphereListItemDTO,
        SphereRepositoryProtocol,
        SphereRole,
        SphereSettingsPatch,
        SphereUpdateData,
    )
    from ludamus.pacts.user import UserRepositoryProtocol


def can_write_programme(
    *,
    users: UserRepositoryProtocol,
    spheres: SphereRepositoryProtocol,
    sphere_id: int,
    user_slug: str,
) -> bool:
    return sphere_access(
        spheres.manager_role(sphere_id, user_slug),
        is_superuser=users.read(user_slug).is_superuser,
    ).allows(Capability.PANEL_WRITE)


class AnnouncementsService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        announcements: AnnouncementsRepositoryProtocol,
        fanout: AnnouncementFanoutSchedulerProtocol,
    ) -> None:
        self._transaction = transaction
        self._announcements = announcements
        self._fanout = fanout

    def list_for_sphere(self, sphere_id: int) -> list[AnnouncementDTO]:
        return self._announcements.list_for_sphere(sphere_id)

    def list_published(self, sphere_id: int) -> list[AnnouncementDTO]:
        return self._announcements.list_published(sphere_id)

    def get(self, sphere_id: int, pk: int) -> AnnouncementDTO:
        return self._announcements.get(sphere_id, pk)

    def create(self, sphere_id: int, data: AnnouncementData) -> AnnouncementDTO:
        with self._transaction.atomic():
            announcement = self._announcements.create(sphere_id, data)
        self._schedule_fanout(announcement)
        return announcement

    def update(
        self, sphere_id: int, pk: int, data: AnnouncementData
    ) -> AnnouncementDTO:
        with self._transaction.atomic():
            announcement = self._announcements.update(sphere_id, pk, data)
        self._schedule_fanout(announcement)
        return announcement

    def _schedule_fanout(self, announcement: AnnouncementDTO) -> None:
        # Published and never notified — whether just created that way or a
        # draft flipped by an edit. The fanout itself re-checks and stamps
        # notified_at atomically, so a duplicate schedule is harmless.
        if announcement.is_published and announcement.notified_at is None:
            self._fanout.schedule_fanout(announcement_id=announcement.pk)

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


def _update_data(changes: SphereSettingsPatch) -> SphereUpdateData:
    data: SphereUpdateData = {}
    if "allow_facilitator_session_edit" in changes:
        data["allow_facilitator_session_edit"] = changes[
            "allow_facilitator_session_edit"
        ]
    if "event_cover_buttons_at_bottom" in changes:
        data["event_cover_buttons_at_bottom"] = changes["event_cover_buttons_at_bottom"]
    if "visibility" in changes:
        data["visibility"] = changes["visibility"]
    if (encounters_policy := changes.get("encounters_policy")) is not None:
        data["encounters_policy"] = encounters_policy.value
    if "parley_enabled" in changes:
        data["parley_enabled"] = changes["parley_enabled"]
    if "parley_organizers_enabled" in changes:
        data["parley_organizers_enabled"] = changes["parley_organizers_enabled"]
    if "parley_events_enabled" in changes:
        data["parley_events_enabled"] = changes["parley_events_enabled"]
    return data


def _closes_chat(current: SphereDTO, data: SphereUpdateData) -> bool:
    """Whether the change turns off a part of the chat that passes still name.

    The sphere's chat, its organizers' room and its events' chats each live
    in the passes already issued until those are taken back.
    """
    return (
        (data.get("parley_enabled") is False and current.parley_enabled)
        or (
            data.get("parley_organizers_enabled") is False
            and current.parley_organizers_enabled
        )
        or (
            data.get("parley_events_enabled") is False and current.parley_events_enabled
        )
    )


class SpherePanelService:
    """Read-side context loader for the sphere panel."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        spheres: SphereRepositoryProtocol,
        events: EventRepositoryProtocol,
        encounters: EncounterRepositoryProtocol,
        users: UserRepositoryProtocol,
        chat: ParleyRevocationServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._spheres = spheres
        self._events = events
        self._encounters = encounters
        self._users = users
        self._chat = chat

    def manager_role(self, sphere_id: int, user_slug: str) -> SphereRole | None:
        return self._spheres.manager_role(sphere_id, user_slug)

    def can_write_programme(self, sphere_id: int, user_slug: str) -> bool:
        return can_write_programme(
            users=self._users,
            spheres=self._spheres,
            sphere_id=sphere_id,
            user_slug=user_slug,
        )

    def access(
        self, sphere_id: int, user_slug: str, *, is_superuser: bool
    ) -> SphereAccessDTO:
        return sphere_access(
            self._spheres.manager_role(sphere_id, user_slug), is_superuser=is_superuser
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
        chat: SphereChatSettings,
        event_cover_buttons_at_bottom: bool,
        encounters_policy: EncountersPolicy,
        logo: UploadedFileProtocol | str | None = None,
        confirmed_encounters_disable: bool = False,
    ) -> SphereSettingsOutcome:
        """Save the settings the caller named, refusing an unconfirmed hide.

        Every argument is a patch: None means "leave this as it stands", and
        a caller that only wants to swap the logo says so rather than reading
        the other two and handing them back. That read-then-write is a lost
        update waiting to happen — between the read and the write another
        manager changes the policy, and the stale value overwrites theirs.

        This closes the hazard for a partial write, which is what the MCP
        tools do. A full form still asserts every field it carries, so the
        panel keeps last-write-wins; closing that needs a version round-
        tripped through the form. The confirmation gate below is likewise
        check-then-act, but losing that race costs a round trip, not data.

        Returns:
            NEEDS_CONFIRMATION when the save would turn encounters off while
            the sphere still has some — nothing is written, and the caller is
            expected to warn and ask again. SAVED otherwise.
        """
        data: SphereUpdateData = {
            "allow_facilitator_session_edit": allow_facilitator_session_edit,
            "parley_enabled": chat["parley_enabled"],
            "parley_organizers_enabled": chat["parley_organizers_enabled"],
            "parley_events_enabled": chat["parley_events_enabled"],
            "event_cover_buttons_at_bottom": event_cover_buttons_at_bottom,
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
            if _closes_chat(self._spheres.read(sphere_id), data):
                self._chat.revoke_sphere(sphere_id=sphere_id)
            self._spheres.update(sphere_id, data)
            return SphereSettingsOutcome.SAVED

    def patch_settings(
        self,
        sphere_id: int,
        *,
        changes: SphereSettingsPatch,
        confirmed_encounters_disable: bool = False,
    ) -> SphereSettingsOutcome:
        data = _update_data(changes)
        encounters_policy = changes.get("encounters_policy")
        with self._transaction.atomic():
            if (
                not confirmed_encounters_disable
                and encounters_policy is EncountersPolicy.NONE
                and self._spheres.read(sphere_id).encounters_policy
                is not EncountersPolicy.NONE
                and self._encounters.exists_for_sphere(sphere_id)
            ):
                return SphereSettingsOutcome.NEEDS_CONFIRMATION
            if _closes_chat(self._spheres.read(sphere_id), data):
                self._chat.revoke_sphere(sphere_id=sphere_id)
            if data:
                self._spheres.update(sphere_id, data)
            return SphereSettingsOutcome.SAVED

    def event_chat_on(self, *, sphere_id: int, event: EventDTO) -> bool:
        sphere = self._spheres.read(sphere_id)
        return event_chat_on(
            sphere_chat=sphere.parley_enabled,
            own=event.parley_enabled,
            sphere_default=sphere.parley_events_enabled,
        )

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
