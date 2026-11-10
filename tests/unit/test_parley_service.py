from datetime import UTC, datetime
from unittest.mock import Mock

from ludamus.mills.parley import (
    ParleyRevocationService,
    ParleyService,
    sign_revocations,
)
from ludamus.pacts.parley import (
    REVOKE_EVERYONE,
    ParleyAccessDTO,
    ParleyCapabilityClaims,
    ParleyReportData,
    ParleyRoomDTO,
    ParleyRoomKind,
)
from ludamus.specs.parley import PARLEY_TOKEN_LIFETIME


def test_bootstrap_signs_a_member_role_with_their_own_sessions() -> None:
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    access = ParleyAccessDTO(
        sphere_id=45,
        sphere_name="Bachanalia",
        user_id=123,
        user_name="Ada",
        user_avatar_url="https://example.com/ada.png",
        rooms=[
            ParleyRoomDTO(
                id="sphere:45",
                kind=ParleyRoomKind.SPHERE,
                title="Bachanalia",
                can_write=True,
            ),
            ParleyRoomDTO(
                id="session:45:981",
                kind=ParleyRoomKind.SESSION,
                title="Mothership",
                can_write=False,
                session_id=981,
                ends_at=1_786_000_000,
            ),
        ],
        is_manager=False,
    )
    repository = Mock()
    repository.read_access.return_value = access
    signer = Mock()
    signer.sign.return_value = "signed-token"
    service = ParleyService(
        repository=repository, signer=signer, agent_host="parley.example.com"
    )

    result = service.bootstrap(sphere_id=45, user_id=123, now=now)

    assert result is not None
    assert result.model_dump(mode="json", by_alias=True) == {
        "sphere": {"id": "45", "name": "Bachanalia"},
        "user": {
            "id": "123",
            "name": "Ada",
            "avatarUrl": "https://example.com/ada.png",
        },
        "rooms": [
            {
                "id": "sphere:45",
                "kind": "sphere",
                "title": "Bachanalia",
                "canWrite": True,
                "canModerate": False,
            },
            {
                "id": "session:45:981",
                "kind": "session",
                "title": "Mothership",
                "canWrite": False,
                "canModerate": False,
            },
        ],
        "capabilityToken": "signed-token",
        "agentHost": "parley.example.com",
    }
    repository.read_access.assert_called_once()
    assert repository.read_access.call_args.kwargs["sphere_id"] == access.sphere_id
    assert repository.read_access.call_args.kwargs["user_id"] == access.user_id
    assert repository.read_access.call_args.kwargs["window"].now == now
    claims = signer.sign.call_args.args[0]
    assert isinstance(claims, ParleyCapabilityClaims)
    assert claims.model_dump(exclude={"jti"}) == {
        "iss": "ludamus",
        "aud": "parley",
        "sub": "123",
        "sphere": "45",
        "name": "Ada",
        "avatar": "https://example.com/ada.png",
        "role": "member",
        "sessions": {"981": {"endsAt": 1_786_000_000, "writable": False}},
        "readOnlyAfter": 48 * 3600,
        "retainFor": 30 * 24 * 3600,
        "iat": 1_786_017_600,
        "exp": 1_786_017_600 + 12 * 3600,
    }
    assert claims.jti


def test_bootstrap_signs_a_manager_role_without_listing_rooms() -> None:
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    repository = Mock()
    repository.read_access.return_value = ParleyAccessDTO(
        sphere_id=45,
        sphere_name="Bachanalia",
        user_id=123,
        user_name="Ada",
        user_avatar_url="",
        rooms=[
            ParleyRoomDTO(
                id="sphere:45",
                kind=ParleyRoomKind.SPHERE,
                title="Bachanalia",
                can_write=True,
            ),
            *(
                ParleyRoomDTO(
                    id=f"session:45:{pk}",
                    kind=ParleyRoomKind.SESSION,
                    title=f"Session {pk}",
                    can_write=True,
                    can_moderate=True,
                    session_id=pk,
                    ends_at=1_786_000_000,
                )
                for pk in range(1, 1001)
            ),
        ],
        is_manager=True,
    )
    signer = Mock()
    signer.sign.return_value = "signed-token"
    service = ParleyService(
        repository=repository, signer=signer, agent_host="parley.example.com"
    )

    service.bootstrap(sphere_id=45, user_id=123, now=now)

    claims = signer.sign.call_args.args[0]
    assert claims.role == "manager"
    assert claims.sessions == {}


def test_bootstrap_stops_when_repository_denies_access() -> None:
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    repository = Mock()
    repository.read_access.return_value = None
    signer = Mock()
    service = ParleyService(
        repository=repository, signer=signer, agent_host="parley.example.com"
    )

    result = service.bootstrap(sphere_id=45, user_id=123, now=now)

    assert result is None
    repository.read_access.assert_called_once()
    assert repository.read_access.call_args.kwargs["window"].now == now
    signer.sign.assert_not_called()


def test_report_message_returns_what_the_repository_stored() -> None:
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    repository = Mock()
    repository.create_report.return_value = False
    service = ParleyService(
        repository=repository, signer=Mock(), agent_host="parley.example.com"
    )
    data = ParleyReportData(
        sphere_id=45, user_id=123, room_id="sphere:45", message_id=7, reason="spam"
    )

    created = service.report_message(data=data, now=now)

    assert created is False
    assert repository.create_report.call_args.kwargs["window"].now == now


class FakeChatSpheres:
    def __init__(self, *, event_spheres=None, chat_spheres=()):
        self._event_spheres = event_spheres or {}
        self._chat_spheres = list(chat_spheres)

    def read_event_sphere_id(self, event_id):
        return self._event_spheres.get(event_id)

    def list_chat_sphere_ids(self):
        return self._chat_spheres


class FakeOutbox:
    def __init__(self):
        self.scheduled = []

    def schedule(self, *, sphere_ids, subject):
        self.scheduled.append((sphere_ids, subject))


def _revocations(repository):
    outbox = FakeOutbox()
    return ParleyRevocationService(repository=repository, outbox=outbox), outbox


def test_a_ban_revokes_the_person_in_the_events_sphere_only_when_it_has_chat():
    service, outbox = _revocations(FakeChatSpheres(event_spheres={7: 45}))

    service.revoke_event_user(event_id=7, user_id=123)
    service.revoke_event_user(event_id=8, user_id=123)

    assert outbox.scheduled == [([45], "123")]


def test_a_disabled_account_is_revoked_in_every_sphere_with_chat():
    service, outbox = _revocations(FakeChatSpheres(chat_spheres=[3, 45]))
    nowhere, quiet = _revocations(FakeChatSpheres())

    service.revoke_user(user_id=123)
    nowhere.revoke_user(user_id=123)

    assert outbox.scheduled == [([3, 45], "123")]
    assert not quiet.scheduled


def test_turning_chat_off_revokes_everyone_in_the_sphere():
    service, outbox = _revocations(FakeChatSpheres())

    service.revoke_sphere(sphere_id=45)

    assert outbox.scheduled == [([45], REVOKE_EVERYONE)]


def test_each_sphere_gets_a_revocation_that_outlives_the_passes_it_voids():
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    signed = []

    class Signer:
        @staticmethod
        def sign(claims):
            signed.append(claims)
            return f"token-{claims.sphere}"

    tokens = sign_revocations(
        signer=Signer(), sphere_ids=[3, 45], subject="123", now=now
    )

    assert tokens == ["token-3", "token-45"]
    cutoff = int(now.timestamp())
    for claims in signed:
        assert claims.aud == "parley-revocation"
        assert claims.sub == "123"
        assert claims.revoked_before == cutoff
        assert claims.exp == int((now + PARLEY_TOKEN_LIFETIME).timestamp())
    assert signed[0].jti != signed[1].jti
