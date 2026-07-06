from contextlib import contextmanager
from datetime import UTC, datetime

from ludamus.mills.crowd import CompanionsService, ProfileService
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import ConnectedUserDTO, UserDTO, UserType


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()

    def savepoint(self):
        return _atomic()


def _user_dto(**overrides) -> UserDTO:
    defaults = {
        "avatar_url": "",
        "date_joined": datetime(2024, 1, 1, tzinfo=UTC),
        "discord_username": "",
        "email": "",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": 1,
        "slug": "manager",
        "use_gravatar": False,
        "user_type": UserType.ACTIVE,
        "username": "auth0|sub",
    }
    return UserDTO(**(defaults | overrides))


def _companion_dto(**overrides) -> ConnectedUserDTO:
    defaults = {
        "avatar_url": "",
        "date_joined": datetime(2024, 1, 1, tzinfo=UTC),
        "discord_username": "",
        "email": "",
        "full_name": "",
        "is_active": True,
        "is_authenticated": False,
        "is_staff": False,
        "is_superuser": False,
        "name": "Kid",
        "pk": 2,
        "slug": "kid",
        "use_gravatar": False,
        "user_type": UserType.CONNECTED,
        "username": "connected|kid",
    }
    return ConnectedUserDTO(**(defaults | overrides))


class FakeUsers:
    def __init__(self, *, users=(), existing_emails=()):
        self._users = list(users)
        self._existing_emails = set(existing_emails)
        self.updated = []

    def read(self, slug):
        for user in self._users:
            if user.slug == slug:
                return user
        raise NotFoundError

    def update(self, user_slug, user_data):
        self.updated.append((user_slug, dict(user_data)))
        for index, user in enumerate(self._users):
            if user.slug == user_slug:
                self._users[index] = user.model_copy(update=dict(user_data))

    def email_exists(self, email, exclude_slug=None):
        if not email:
            return False
        return (
            any(
                user.email == email and user.slug != exclude_slug
                for user in self._users
            )
            or email in self._existing_emails
        )


class FakeParticipations:
    def __init__(self, counts=None):
        self._counts = counts or {}

    def confirmed_count(self, user_id):
        return self._counts.get(user_id, 0)


class FakeCompanions:
    def __init__(self, *, companions=()):
        self._companions = list(companions)
        self.created = []
        self.updated = []
        self.deleted = []

    def read_all(self, manager_slug):
        _ = manager_slug
        return list(self._companions)

    def read(self, manager_slug, user_slug):
        _ = manager_slug
        for companion in self._companions:
            if companion.slug == user_slug:
                return companion
        raise NotFoundError

    def create(self, manager_slug, user_data):
        self.created.append((manager_slug, dict(user_data)))

    def update(self, manager_slug, user_slug, user_data):
        self.updated.append((manager_slug, user_slug, dict(user_data)))

    def delete(self, manager_slug, user_slug):
        self.deleted.append((manager_slug, user_slug))


def _fake_gravatar(email):
    return f"https://gravatar/{email}" if email else None


def _profile_service(*, users, participations=None, transaction=None):
    return ProfileService(
        transaction=transaction or FakeTransaction(),
        users=users,
        participations=participations or FakeParticipations(),
        avatar_url=_fake_gravatar,
    )


class TestProfileService:
    def test_read_returns_user(self):
        service = _profile_service(users=FakeUsers(users=[_user_dto()]))

        assert service.read("manager").slug == "manager"

    def test_confirmed_participations_count_delegates(self):
        expected = 3
        service = _profile_service(
            users=FakeUsers(), participations=FakeParticipations({7: expected})
        )

        assert service.confirmed_participations_count(7) == expected

    def test_email_in_use_excludes_own_slug(self):
        users = FakeUsers(users=[_user_dto(email="mine@example.com")])
        service = _profile_service(users=users)

        assert service.email_in_use("mine@example.com", exclude_slug="manager") is False
        assert service.email_in_use("mine@example.com", exclude_slug="other") is True

    def test_update_writes_in_transaction(self):
        users = FakeUsers(users=[_user_dto()])
        transaction = FakeTransaction()
        service = _profile_service(users=users, transaction=transaction)

        service.update("manager", {"name": "New Name"})

        assert transaction.entered == 1
        assert users.updated == [("manager", {"name": "New Name"})]

    def test_read_avatar_builds_dto(self):
        users = FakeUsers(
            users=[_user_dto(email="a@b.c", avatar_url="https://auth0/pic")]
        )
        service = _profile_service(users=users)

        avatar = service.read_avatar("manager")

        assert avatar.user.slug == "manager"
        assert avatar.gravatar_url == "https://gravatar/a@b.c"
        assert avatar.has_auth0_avatar is True

    def test_read_avatar_without_auth0_picture(self):
        service = _profile_service(users=FakeUsers(users=[_user_dto(email="")]))

        avatar = service.read_avatar("manager")

        assert avatar.gravatar_url is None
        assert avatar.has_auth0_avatar is False

    def test_set_avatar_preference_writes_in_transaction(self):
        users = FakeUsers(users=[_user_dto()])
        transaction = FakeTransaction()
        service = _profile_service(users=users, transaction=transaction)

        service.set_avatar_preference("manager", use_gravatar=True)

        assert transaction.entered == 1
        assert users.updated == [("manager", {"use_gravatar": True})]


class TestCompanionsService:
    def test_list_companions_delegates(self):
        companions = FakeCompanions(companions=[_companion_dto()])
        service = CompanionsService(FakeTransaction(), companions)

        result = service.list_companions("manager")

        assert [c.slug for c in result] == ["kid"]

    def test_read_delegates(self):
        companions = FakeCompanions(companions=[_companion_dto()])
        service = CompanionsService(FakeTransaction(), companions)

        assert service.read(manager_slug="manager", user_slug="kid").slug == "kid"

    def test_create_writes_in_transaction(self):
        companions = FakeCompanions()
        transaction = FakeTransaction()
        service = CompanionsService(transaction, companions)

        service.create(manager_slug="manager", user_data={"name": "Kid"})

        assert transaction.entered == 1
        assert companions.created == [("manager", {"name": "Kid"})]

    def test_update_writes_in_transaction(self):
        companions = FakeCompanions(companions=[_companion_dto()])
        transaction = FakeTransaction()
        service = CompanionsService(transaction, companions)

        service.update(
            manager_slug="manager", user_slug="kid", user_data={"name": "Grown"}
        )

        assert transaction.entered == 1
        assert companions.updated == [("manager", "kid", {"name": "Grown"})]

    def test_delete_writes_in_transaction(self):
        companions = FakeCompanions(companions=[_companion_dto()])
        transaction = FakeTransaction()
        service = CompanionsService(transaction, companions)

        service.delete(manager_slug="manager", user_slug="kid")

        assert transaction.entered == 1
        assert companions.deleted == [("manager", "kid")]
