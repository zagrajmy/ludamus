from django.db import IntegrityError
from django.db.models import ProtectedError

from ludamus.adapters.db.django.models import Announcement, Connection, Sphere
from ludamus.pacts import (
    NotFoundError,
    SphereDTO,
    SphereRepositoryProtocol,
    SphereUpdateData,
)
from ludamus.pacts.crowd import SphereDomainRepositoryProtocol, UserDTO
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    AnnouncementsRepositoryProtocol,
    ConnectionDTO,
    ConnectionInUseError,
    ConnectionsRepositoryProtocol,
    DuplicateConnectionDisplayNameError,
    SphereDirectoryRepositoryProtocol,
    SphereListItemDTO,
)


class SphereRepository(
    SphereRepositoryProtocol,
    SphereDirectoryRepositoryProtocol,
    SphereDomainRepositoryProtocol,
):
    @staticmethod
    def domain_exists(domain: str) -> bool:
        return Sphere.objects.filter(site__domain=domain).exists()

    @staticmethod
    def list_all() -> list[SphereListItemDTO]:
        return [
            SphereListItemDTO(pk=sphere.pk, name=sphere.name, domain=sphere.site.domain)
            for sphere in Sphere.objects.select_related("site").order_by("name")
        ]

    @staticmethod
    def read_by_domain(domain: str) -> SphereDTO:
        try:
            sphere = Sphere.objects.select_related("site").get(site__domain=domain)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        return SphereDTO.model_validate(sphere)

    @staticmethod
    def read(pk: int) -> SphereDTO:
        try:
            sphere = Sphere.objects.select_related("site").get(id=pk)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        return SphereDTO.model_validate(sphere)

    @staticmethod
    def is_manager(sphere_id: int, user_slug: str) -> bool:
        return Sphere.objects.filter(id=sphere_id, managers__slug=user_slug).exists()

    @staticmethod
    def list_managers(sphere_id: int) -> list[UserDTO]:
        try:
            sphere = Sphere.objects.get(pk=sphere_id)
        except Sphere.DoesNotExist as err:
            raise NotFoundError from err
        return [UserDTO.model_validate(u) for u in sphere.managers.order_by("name")]

    @staticmethod
    def update(sphere_id: int, data: SphereUpdateData) -> None:
        try:
            sphere = Sphere.objects.get(id=sphere_id)
        except Sphere.DoesNotExist as exception:
            raise NotFoundError from exception

        for key, value in data.items():
            setattr(sphere, key, value)
        sphere.save(update_fields=list(data.keys()))


_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = "connection_unique_display_name_per_sphere"
_SQLITE_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT = (
    "UNIQUE constraint failed: connection.sphere_id, connection.display_name"
)


def is_connection_display_name_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.__cause__, "diag", None)
    if (
        getattr(diag, "constraint_name", None)
        == _CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT
    ):
        return True
    message = str(exc)
    return (
        _CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT in message
        or _SQLITE_CONNECTION_UNIQUE_DISPLAY_NAME_CONSTRAINT in message
    )


class AnnouncementsRepository(AnnouncementsRepositoryProtocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[AnnouncementDTO]:
        return [
            AnnouncementDTO.model_validate(a)
            for a in Announcement.objects.filter(sphere_id=sphere_id)
        ]

    @staticmethod
    def list_published(sphere_id: int) -> list[AnnouncementDTO]:
        return [
            AnnouncementDTO.model_validate(a)
            for a in Announcement.objects.filter(sphere_id=sphere_id, is_published=True)
        ]

    @staticmethod
    def get(sphere_id: int, pk: int) -> AnnouncementDTO:
        try:
            announcement = Announcement.objects.get(pk=pk, sphere_id=sphere_id)
        except Announcement.DoesNotExist as exc:
            raise NotFoundError from exc
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def create(sphere_id: int, data: AnnouncementData) -> AnnouncementDTO:
        announcement = Announcement.objects.create(
            sphere_id=sphere_id,
            title=data.title,
            content=data.content,
            is_published=data.is_published,
        )
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def update(sphere_id: int, pk: int, data: AnnouncementData) -> AnnouncementDTO:
        try:
            announcement = Announcement.objects.get(pk=pk, sphere_id=sphere_id)
        except Announcement.DoesNotExist as exc:
            raise NotFoundError from exc
        announcement.title = data.title
        announcement.content = data.content
        announcement.is_published = data.is_published
        announcement.save(
            update_fields=["title", "content", "is_published", "modification_time"]
        )
        return AnnouncementDTO.model_validate(announcement)

    @staticmethod
    def delete(sphere_id: int, pk: int) -> None:
        deleted, _ = Announcement.objects.filter(pk=pk, sphere_id=sphere_id).delete()
        if not deleted:
            raise NotFoundError


class ConnectionsRepository(ConnectionsRepositoryProtocol):
    @staticmethod
    def list_for_sphere(sphere_id: int) -> list[ConnectionDTO]:
        return [
            ConnectionDTO.model_validate(c)
            for c in Connection.objects.filter(sphere_id=sphere_id).order_by(
                "display_name"
            )
        ]

    @staticmethod
    def get(sphere_id: int, pk: int) -> ConnectionDTO:
        try:
            connection = Connection.objects.get(pk=pk, sphere_id=sphere_id)
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def create(sphere_id: int, display_name: str) -> ConnectionDTO:
        try:
            connection = Connection.objects.create(
                sphere_id=sphere_id, display_name=display_name
            )
        except IntegrityError as exc:
            if is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update(sphere_id: int, pk: int, display_name: str) -> ConnectionDTO:
        try:
            connection = Connection.objects.get(pk=pk, sphere_id=sphere_id)
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        connection.display_name = display_name
        try:
            connection.save(update_fields=["display_name"])
        except IntegrityError as exc:
            if is_connection_display_name_conflict(exc):
                raise DuplicateConnectionDisplayNameError from exc
            raise
        return ConnectionDTO.model_validate(connection)

    @staticmethod
    def update_secret(sphere_id: int, pk: int, blob: bytes) -> None:
        updated = Connection.objects.filter(pk=pk, sphere_id=sphere_id).update(
            secret=blob
        )
        if not updated:
            raise NotFoundError

    @staticmethod
    def read_secret(sphere_id: int, pk: int) -> bytes:
        try:
            connection = Connection.objects.only("secret").get(
                pk=pk, sphere_id=sphere_id
            )
        except Connection.DoesNotExist as exc:
            raise NotFoundError from exc
        return bytes(connection.secret)

    @staticmethod
    def delete(sphere_id: int, pk: int) -> None:
        try:
            deleted, _ = Connection.objects.filter(pk=pk, sphere_id=sphere_id).delete()
        except ProtectedError as exc:
            raise ConnectionInUseError from exc
        if not deleted:
            raise NotFoundError
