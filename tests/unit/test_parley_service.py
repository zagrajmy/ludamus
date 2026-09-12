from datetime import UTC, datetime
from unittest.mock import Mock

from ludamus.mills.parley import ParleyService
from ludamus.pacts.parley import (
    ParleyAccessDTO,
    ParleyCapabilityClaims,
    ParleyRoomDTO,
    ParleyRoomKind,
)


def test_bootstrap_signs_exact_room_permissions() -> None:
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
                id="session:981",
                kind=ParleyRoomKind.SESSION,
                title="Mothership",
                can_write=False,
                read_only_at=1_786_000_000,
                delete_at=1_788_000_000,
            ),
        ],
        moderated_room_ids=["sphere:45"],
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
                "id": "session:981",
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
        "rooms": ["sphere:45", "session:981"],
        "writes": ["sphere:45"],
        "moderates": ["sphere:45"],
        "lifecycle": {
            "session:981": {"readOnlyAt": 1_786_000_000, "deleteAt": 1_788_000_000}
        },
        "iat": 1_786_017_600,
        "exp": 1_786_018_500,
    }
    assert claims.jti


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
