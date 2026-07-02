from typing import TYPE_CHECKING

from django.contrib.auth.hashers import make_password

from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    ClaimableProfileDTO,
    ClaimRepositoryProtocol,
    ConnectedUserRepositoryProtocol,
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


class ClaimRepository(ClaimRepositoryProtocol):
    @staticmethod
    def issue_token(*, manager_slug: str, user_slug: str, token: str) -> bool:
        updated = User.objects.filter(
            slug=user_slug, manager__slug=manager_slug, user_type=UserType.CONNECTED
        ).update(claim_token=token)
        return bool(updated)

    @staticmethod
    def read_claimable(token: str) -> ClaimableProfileDTO | None:
        if not token:
            return None
        user = (
            User.objects.filter(claim_token=token, user_type=UserType.CONNECTED)
            .select_related("manager")
            .first()
        )
        if user is None:
            return None
        return ClaimableProfileDTO(
            name=user.name,
            slug=user.slug,
            manager_name=user.manager.name if user.manager else "",
        )

    @staticmethod
    def username_exists(username: str) -> bool:
        return User.objects.filter(username=username).exists()

    @staticmethod
    def convert(*, token: str, username: str) -> str | None:
        # Email/avatar from the provider are applied afterwards by the login
        # callback's _apply_user_updates (with its own collision handling), so
        # this stays a pure identity flip and never duplicates that rule.
        user = User.objects.filter(
            claim_token=token, user_type=UserType.CONNECTED
        ).first()
        if user is None:
            return None
        user.username = username
        user.user_type = UserType.ACTIVE
        user.manager = None
        user.password = make_password(None)
        user.claim_token = ""
        user.save()
        return user.slug
