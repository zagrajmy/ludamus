import base64
from http import HTTPStatus

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SphereFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.parley.helpers import decode_segment

# NOTE: browsers drop a cookie whose name, value and attributes pass 4096
# bytes, and the Worker stores the token as one; half leaves room for a long
# name and avatar URL.
COOKIE_BUDGET = 2048


@pytest.mark.usefixtures("parley_settings")
def test_anonymous_bootstrap_is_unauthorized(client):
    response = client.get(reverse("parley_bootstrap"))

    assert_response(
        response,
        HTTPStatus.UNAUTHORIZED,
        content=b'{"error": "authentication_required"}',
    )


@pytest.mark.usefixtures("parley_settings")
def test_disabled_sphere_is_not_found(authenticated_client, sphere):
    sphere.parley_enabled = False
    sphere.save()

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(
        response, HTTPStatus.NOT_FOUND, content=b'{"error": "parley_unavailable"}'
    )


def test_returns_scoped_rooms_and_verifiable_capability(
    authenticated_client, active_user, event, parley_settings, sphere
):
    sphere.parley_enabled = True
    sphere.save()
    confirmed = SessionFactory(
        event=event, category=None, title="Mothership", status=SessionStatus.ACCEPTED
    )
    SessionParticipationFactory(
        session=confirmed, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )
    waiting = SessionFactory(event=event, category=None, title="Secret waitlist")
    SessionParticipationFactory(
        session=waiting, user=active_user, status=SessionParticipationStatus.WAITING
    )
    facilitated = SessionFactory(event=event, category=None, title="Workshop")
    facilitator = Facilitator.objects.create(
        event=event, user=active_user, display_name=active_user.name, slug="test-user"
    )
    facilitated.facilitators.add(facilitator)
    SessionFactory(
        event=EventFactory(sphere=SphereFactory()), category=None, title="Foreign"
    )

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert payload["sphere"] == {"id": str(sphere.pk), "name": sphere.name}
    assert payload["user"] == {
        "id": str(active_user.pk),
        "name": active_user.name,
        "avatarUrl": "",
    }
    assert payload["rooms"] == [
        {
            "id": f"sphere:{sphere.pk}",
            "kind": "sphere",
            "title": sphere.name,
            "canWrite": True,
            "canModerate": False,
            "sessionId": None,
        },
        {
            "id": f"session:{sphere.pk}:{confirmed.pk}",
            "kind": "session",
            "title": "Mothership",
            "canWrite": True,
            "canModerate": False,
            "sessionId": confirmed.pk,
        },
        {
            "id": f"session:{sphere.pk}:{facilitated.pk}",
            "kind": "session",
            "title": "Workshop",
            "canWrite": False,
            "canModerate": False,
            "sessionId": facilitated.pk,
        },
    ]
    assert payload["agentHost"] == "parley.example.com"
    assert payload["ageUrl"] == "/crowd/profile/privacy/"
    header, body, signature = payload["capabilityToken"].split(".")
    assert decode_segment(header) == {"alg": "RS256", "typ": "JWT"}
    claims = decode_segment(body)
    assert claims["iss"] == "ludamus"
    assert claims["aud"] == "parley"
    assert claims["sub"] == str(active_user.pk)
    assert claims["sphere"] == str(sphere.pk)
    ends_at = int(event.end_time.timestamp())
    assert claims["role"] == "member"
    assert claims["sessions"] == {
        str(confirmed.pk): {"endsAt": ends_at, "writable": True},
        str(facilitated.pk): {"endsAt": ends_at, "writable": False},
    }
    assert claims["readOnlyAfter"] == 48 * 3600
    assert claims["retainFor"] == 30 * 24 * 3600
    parley_settings.verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


@pytest.mark.usefixtures("parley_settings")
def test_manager_token_does_not_grow_with_the_sphere(
    authenticated_client, active_user, event, sphere
):
    sphere.parley_enabled = True
    sphere.save()
    sphere.managers.add(active_user)
    SessionFactory(event=event, category=None)

    small = authenticated_client.get(reverse("parley_bootstrap")).json()
    SessionFactory.create_batch(200, event=event, category=None)
    large = authenticated_client.get(reverse("parley_bootstrap")).json()

    assert len(large["rooms"]) == len(small["rooms"]) + 200
    assert len(large["capabilityToken"]) == len(small["capabilityToken"])
    assert len(large["capabilityToken"]) < COOKIE_BUDGET
    claims = decode_segment(large["capabilityToken"].split(".")[1])
    assert claims["role"] == "manager"
    assert claims["sessions"] == {}


@pytest.mark.parametrize(
    ("age_band", "can_message", "age_gate"),
    (
        (AgeBand.UNKNOWN, False, "unconfirmed"),
        (AgeBand.THIRTEEN_TO_FIFTEEN, False, "under_16"),
        (AgeBand.SIXTEEN_PLUS, True, None),
    ),
)
@pytest.mark.usefixtures("parley_settings")
def test_says_whether_age_keeps_direct_messages_shut(
    authenticated_client, active_user, sphere, age_band, can_message, age_gate
):
    sphere.parley_enabled = True
    sphere.save()
    active_user.age_band = age_band
    active_user.save()

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert payload["canMessage"] is can_message
    assert payload["ageGate"] == age_gate
