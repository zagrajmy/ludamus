import base64
import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from io import StringIO

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.management import call_command
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    Party,
    PartyMembership,
    SphereMembership,
)
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.party import PartyMembershipStatus
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.sphere import SphereRole
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SphereFactory,
    UserFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.parley.helpers import decode_segment

# NOTE: browsers drop a cookie whose name, value and attributes pass 4096
# bytes, and the Worker stores the token as one; half leaves room for a long
# name and avatar URL.
COOKIE_BUDGET = 2048
HEAVY_EVENTS = 40


@pytest.mark.usefixtures("parley_settings")
def test_anonymous_bootstrap_is_unauthorized(client):
    response = client.get(reverse("parley_bootstrap"))

    assert_response(
        response,
        HTTPStatus.UNAUTHORIZED,
        content=b'{"error": "authentication_required"}',
    )


@pytest.mark.usefixtures("parley_settings")
def test_nowhere_to_chat_is_not_found(authenticated_client, sphere, active_user):
    sphere.managers.add(active_user)
    sphere.parley_enabled = False
    sphere.save()

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(
        response, HTTPStatus.NOT_FOUND, content=b'{"error": "parley_unavailable"}'
    )


def test_returns_scoped_rooms_and_verifiable_capability(
    authenticated_client, active_user, event, parley_settings, sphere
):
    event.parley_enabled = True
    event.save()
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
    elsewhere = SphereFactory()
    elsewhere.managers.add(active_user)

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert payload["user"] == {
        "id": str(active_user.pk),
        "name": active_user.name,
        "avatarUrl": "",
    }
    assert payload["rooms"] == [
        {
            "id": f"organizers:{elsewhere.pk}",
            "kind": "organizers",
            "sphere": elsewhere.pk,
            "title": elsewhere.name,
            "canWrite": True,
            "canModerate": True,
        },
        {
            "id": f"event:{sphere.pk}:{event.pk}",
            "kind": "event",
            "sphere": sphere.pk,
            "title": event.name,
            "canWrite": True,
            "canModerate": False,
        },
        {
            "id": f"session:{sphere.pk}:{confirmed.pk}",
            "kind": "session",
            "sphere": sphere.pk,
            "title": "Mothership",
            "canWrite": True,
            "canModerate": False,
        },
        {
            "id": f"session:{sphere.pk}:{facilitated.pk}",
            "kind": "session",
            "sphere": sphere.pk,
            "title": "Workshop",
            "canWrite": False,
            "canModerate": False,
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
    ends_at = int(event.end_time.timestamp())
    assert claims["managed"] == {str(elsewhere.pk): {"organizers": True}}
    assert claims["events"] == {
        f"{sphere.pk}:{event.pk}": {
            "endsAt": ends_at,
            "writable": True,
            "chat": True,
            "sessions": {str(confirmed.pk): True, str(facilitated.pk): False},
        }
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
def test_manager_token_does_not_grow_with_the_programme(
    authenticated_client, active_user, event, sphere
):
    sphere.managers.add(active_user)
    event.parley_enabled = True
    event.save()
    SessionFactory(event=event, category=None)

    small = authenticated_client.get(reverse("parley_bootstrap")).json()
    SessionFactory.create_batch(200, event=event, category=None)
    large = authenticated_client.get(reverse("parley_bootstrap")).json()

    assert len(large["rooms"]) == len(small["rooms"]) + 200
    assert len(large["capabilityToken"]) == len(small["capabilityToken"])
    claims = decode_segment(large["capabilityToken"].split(".")[1])
    assert claims["managed"] == {str(sphere.pk): {"organizers": True}}
    assert claims["events"] == {
        f"{sphere.pk}:{event.pk}": {
            "endsAt": int(event.end_time.timestamp()),
            "writable": True,
            "chat": True,
            "sessions": {},
        }
    }


@pytest.mark.usefixtures("parley_settings")
def test_a_heavy_participant_s_pass_still_fits_a_cookie(
    authenticated_client, active_user, sphere, caplog
):
    start = datetime.now(UTC) + timedelta(days=1)
    for day in range(HEAVY_EVENTS):
        event = EventFactory(
            sphere=sphere,
            start_time=start + timedelta(days=day),
            end_time=start + timedelta(days=day, hours=8),
            parley_enabled=True,
        )
        for session in SessionFactory.create_batch(
            5, event=event, category=None, status=SessionStatus.ACCEPTED
        ):
            SessionParticipationFactory(
                session=session,
                user=active_user,
                status=SessionParticipationStatus.CONFIRMED,
            )
    caplog.set_level(logging.ERROR, logger="ludamus.mills.parley")

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert len(payload["capabilityToken"]) <= COOKIE_BUDGET
    claims = decode_segment(payload["capabilityToken"].split(".")[1])
    kept = {room["id"] for room in payload["rooms"]}
    assert len(claims["events"]) < HEAVY_EVENTS
    assert {f"event:{key}" for key in claims["events"]} <= kept
    assert "parley pass over its size" in caplog.text


@pytest.mark.usefixtures("parley_settings")
def test_a_sphere_s_comms_member_moderates_nothing(
    authenticated_client, active_user, event, sphere
):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )
    session = SessionFactory(event=event, category=None)
    SessionParticipationFactory(
        session=session, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert [(room["kind"], room["canModerate"]) for room in payload["rooms"]] == [
        ("session", False)
    ]
    assert decode_segment(payload["capabilityToken"].split(".")[1])["managed"] == {}


@pytest.mark.usefixtures("parley_settings")
def test_a_party_made_before_party_chats_has_one_once_they_open(
    authenticated_client, active_user
):
    active_user.age_band = AgeBand.SIXTEEN_PLUS
    active_user.save()
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    party = Party.objects.create(leader=friend, name="Drużyna Pierścienia")
    for member in (friend, active_user):
        PartyMembership.objects.create(
            party=party, member=member, status=PartyMembershipStatus.ACTIVE
        )

    call_command("open_parley_party_chats", stdout=StringIO())
    again = StringIO()
    call_command("open_parley_party_chats", stdout=again)
    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    assert again.getvalue() == "Synced the chats of 1 parties.\n"
    [chat] = response.json()["conversations"]
    assert (chat["kind"], chat["title"], chat["canWrite"]) == (
        "party",
        "Drużyna Pierścienia",
        True,
    )
    assert {person["id"] for person in chat["members"]} == {
        str(friend.pk),
        str(active_user.pk),
    }


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
    sphere.managers.add(active_user)
    active_user.age_band = age_band
    active_user.save()

    response = authenticated_client.get(reverse("parley_bootstrap"))

    assert_response(response, HTTPStatus.OK)
    payload = response.json()
    assert payload["canMessage"] is can_message
    assert payload["ageGate"] == age_gate
