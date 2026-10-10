from typing import TYPE_CHECKING

import pytest

from ludamus.mills.crowd import CompanionsService, ProfileService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import CompanionDTO
from tests.unit.factories import FakeTransaction, user_dto

_CONFIRMED_COUNT = 3

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO


def _user_dto(**overrides) -> UserDTO:
    return user_dto(**{"slug": "auth0user", **overrides})


class FakeUsers:
    def __init__(self, *, users=()):
        self._users = {user.slug: user for user in users}

    def read(self, slug):
        if slug not in self._users:
            raise NotFoundError
        return self._users[slug]

    def update(self, user_slug, user_data):
        self._users[user_slug] = self._users[user_slug].model_copy(
            update=dict(user_data)
        )


class FakeParticipations:
    @staticmethod
    def confirmed_count(user_id):
        return {1: _CONFIRMED_COUNT}.get(user_id, 0)


class FakeCompanions:
    def __init__(self):
        self.rows = {}

    def create(self, manager_slug, user_data):
        self.rows[manager_slug, user_data["slug"]] = CompanionDTO(
            **dict(_user_dto(slug=user_data["slug"], name=user_data.get("name", "")))
        )

    def read_all(self, manager_slug):
        return [
            dto for (manager, _), dto in self.rows.items() if manager == manager_slug
        ]

    def read(self, manager_slug, user_slug):
        try:
            return self.rows[manager_slug, user_slug]
        except KeyError:
            raise NotFoundError from None

    def delete(self, manager_slug, user_slug):
        del self.rows[manager_slug, user_slug]

    def update(self, manager_slug, user_slug, user_data):
        row = self.rows[manager_slug, user_slug]
        self.rows[manager_slug, user_slug] = row.model_copy(update=dict(user_data))


def _profile_service(users, avatar_url=None):
    return ProfileService(
        transaction=FakeTransaction(),
        users=users,
        participations=FakeParticipations(),
        avatar_url=avatar_url or (lambda email: f"https://gravatar/{email}"),
    )


class TestProfileService:
    def test_read_returns_the_user(self):
        users = FakeUsers(users=[_user_dto()])

        assert _profile_service(users).read("auth0user").slug == "auth0user"

    def test_read_unknown_user_raises(self):
        with pytest.raises(NotFoundError):
            _profile_service(FakeUsers()).read("nobody")

    def test_confirmed_participations_count(self):
        service = _profile_service(FakeUsers())

        assert service.confirmed_participations_count(1) == _CONFIRMED_COUNT
        assert service.confirmed_participations_count(2) == 0

    def test_update_writes_the_data(self):
        users = FakeUsers(users=[_user_dto()])

        _profile_service(users).update("auth0user", {"name": "Renamed"})

        assert users.read("auth0user").name == "Renamed"

    def test_read_avatar_with_provider_picture(self):
        users = FakeUsers(
            users=[_user_dto(email="me@example.com", avatar_url="https://cdn/pic")]
        )

        page = _profile_service(users).read_avatar("auth0user")

        assert page.user.slug == "auth0user"
        assert page.gravatar_url == "https://gravatar/me@example.com"
        assert page.has_provider_avatar is True

    def test_read_avatar_without_provider_picture_or_gravatar(self):
        users = FakeUsers(users=[_user_dto()])

        page = _profile_service(users, avatar_url=lambda _email: None).read_avatar(
            "auth0user"
        )

        assert page.gravatar_url is None
        assert page.has_provider_avatar is False

    def test_set_avatar_preference(self):
        users = FakeUsers(users=[_user_dto()])

        _profile_service(users).set_avatar_preference("auth0user", use_gravatar=True)

        assert users.read("auth0user").use_gravatar is True


class TestCompanionsService:
    @staticmethod
    def _service():
        companions = FakeCompanions()
        return CompanionsService(FakeTransaction(), companions), companions

    def test_create_then_list_scoped_to_manager(self):
        service, _ = self._service()
        service.create(manager_slug="parent", user_data={"slug": "kid", "name": "Kid"})
        service.create(manager_slug="other", user_data={"slug": "stranger"})

        listed = service.list_companions("parent")

        assert [dto.slug for dto in listed] == ["kid"]
        assert listed[0].name == "Kid"

    def test_read_is_scoped_to_manager(self):
        service, _ = self._service()
        service.create(manager_slug="parent", user_data={"slug": "kid"})

        assert service.read(manager_slug="parent", user_slug="kid").slug == "kid"
        with pytest.raises(NotFoundError):
            service.read(manager_slug="other", user_slug="kid")

    def test_update_changes_the_row(self):
        service, _ = self._service()
        service.create(manager_slug="parent", user_data={"slug": "kid"})

        service.update(
            manager_slug="parent", user_slug="kid", user_data={"name": "Renamed"}
        )

        assert service.read(manager_slug="parent", user_slug="kid").name == "Renamed"

    def test_delete_removes_the_row(self):
        service, companions = self._service()
        service.create(manager_slug="parent", user_data={"slug": "kid"})

        service.delete(manager_slug="parent", user_slug="kid")

        assert not companions.rows
