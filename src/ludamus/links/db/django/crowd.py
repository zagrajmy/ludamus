from typing import TYPE_CHECKING

from ludamus.pacts import (
    ConnectedUserRepositoryProtocol,
    NotFoundError,
    UserData,
    UserDTO,
    UserRepositoryProtocol,
    UserType,
)

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


class UserRepository(UserRepositoryProtocol):
    def __init__(self, user_type: UserType) -> None:
        self._user_type = user_type

    @staticmethod
    def create(user_data: UserData) -> None:
        User.objects.create(**user_data)

    def read(self, slug: str) -> UserDTO:
        try:
            user = User.objects.get(slug=slug, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception

        return UserDTO.model_validate(user)

    def read_by_id(self, pk: int) -> UserDTO:
        try:
            user = User.objects.get(pk=pk, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    def read_by_username(self, username: str) -> UserDTO:
        try:
            user = User.objects.get(username=username, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None:
        User.objects.filter(slug=user_slug).update(**user_data)

    @staticmethod
    def email_exists(email: str, exclude_slug: str | None = None) -> bool:
        if not email:
            return False

        query = User.objects.filter(email__iexact=email)
        if exclude_slug:
            query = query.exclude(slug=exclude_slug)

        return query.exists()


class ConnectedUserRepository(ConnectedUserRepositoryProtocol):
    @staticmethod
    def read_all(manager_slug: str) -> list[UserDTO]:
        try:
            manager = User.objects.get(user_type=UserType.ACTIVE, slug=manager_slug)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception

        return [
            UserDTO.model_validate(connected_user)
            for connected_user in manager.connected.all()
        ]

    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None:
        manager = User.objects.get(user_type=UserType.ACTIVE, slug=manager_slug)
        User.objects.create(manager=manager, **user_data)

    @staticmethod
    def read(manager_slug: str, user_slug: str) -> UserDTO:
        try:
            connected_user = User.objects.get(
                slug=user_slug, manager__slug=manager_slug
            )
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(connected_user)

    @staticmethod
    def update(manager_slug: str, user_slug: str, user_data: UserData) -> None:
        User.objects.filter(slug=user_slug, manager__slug=manager_slug).update(
            **user_data
        )

    @staticmethod
    def delete(manager_slug: str, user_slug: str) -> None:
        try:
            user = User.objects.get(slug=user_slug, manager__slug=manager_slug)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        user.delete()
