import base64
import json
from http import HTTPStatus

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator
from ludamus.pacts import SessionParticipationStatus, SessionStatus
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SphereFactory,
)
from tests.integration.utils import assert_response


@pytest.fixture(autouse=True)
def parley_settings(settings):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings.PARLEY_AGENT_HOST = "parley.example.com"
    settings.PARLEY_SIGNING_PRIVATE_KEY = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return private_key.public_key()


def _decode_segment(value: str) -> dict[str, object]:
    padded = value + "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_anonymous_bootstrap_is_unauthorized(client):
    response = client.get(reverse("parley_bootstrap"))

    assert_response(
        response,
        HTTPStatus.UNAUTHORIZED,
        content=b'{"error": "authentication_required"}',
    )


def test_disabled_sphere_is_not_found(authenticated_client):
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
        },
        {
            "id": f"session:{confirmed.pk}",
            "kind": "session",
            "title": "Mothership",
            "canWrite": True,
            "canModerate": False,
        },
        {
            "id": f"session:{facilitated.pk}",
            "kind": "session",
            "title": "Workshop",
            "canWrite": False,
            "canModerate": False,
        },
    ]
    assert payload["agentHost"] == "parley.example.com"
    header, body, signature = payload["capabilityToken"].split(".")
    assert _decode_segment(header) == {"alg": "RS256", "typ": "JWT"}
    claims = _decode_segment(body)
    assert claims["iss"] == "ludamus"
    assert claims["aud"] == "parley"
    assert claims["sub"] == str(active_user.pk)
    assert claims["sphere"] == str(sphere.pk)
    assert claims["rooms"] == [
        f"sphere:{sphere.pk}",
        f"session:{confirmed.pk}",
        f"session:{facilitated.pk}",
    ]
    assert claims["writes"] == [f"sphere:{sphere.pk}", f"session:{confirmed.pk}"]
    parley_settings.verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
