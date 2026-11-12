from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.models import ParleyConversation, ParleyReport
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import SphereFactory, UserFactory
from tests.integration.utils import assert_response

MESSAGE_ID = 42


def test_report_is_scoped_to_an_accessible_room(
    authenticated_client, active_user, sphere
):
    sphere.managers.add(active_user)

    response = authenticated_client.post(
        reverse("parley_report"),
        data={
            "message_id": MESSAGE_ID,
            "reason": "Spam",
            "room_id": f"organizers:{sphere.pk}",
        },
    )

    assert_response(response, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert report.sphere == sphere
    assert report.reporter == active_user
    assert report.room_id == f"organizers:{sphere.pk}"
    assert report.message_id == MESSAGE_ID
    assert report.reason == "Spam"


def test_report_rejects_a_foreign_room_without_side_effects(
    authenticated_client, active_user, sphere
):
    sphere.managers.add(active_user)
    foreign = SphereFactory(parley_enabled=True)

    response = authenticated_client.post(
        reverse("parley_report"),
        data={"message_id": MESSAGE_ID, "room_id": f"organizers:{foreign.pk}"},
    )

    assert_response(response, HTTPStatus.UNPROCESSABLE_CONTENT)
    assert not ParleyReport.objects.exists()


def test_a_party_chat_report_reaches_staff_and_no_sphere(
    authenticated_client, active_user, client, sphere
):
    active_user.age_band = AgeBand.SIXTEEN_PLUS
    active_user.save()
    friend = UserFactory(age_band=AgeBand.SIXTEEN_PLUS)
    services = Services()
    party_pk = services.parties.create(leader_pk=friend.pk, name="Ekipa")
    services.parties.join_via_link(
        token=services.parties.read_invite_token(
            leader_pk=friend.pk, party_pk=party_pk
        ),
        user_pk=active_user.pk,
    )
    chat = ParleyConversation.objects.get(party_id=party_pk)
    sphere.managers.add(friend)

    response = authenticated_client.post(
        reverse("parley_report"),
        data={"message_id": MESSAGE_ID, "room_id": f"conversation:{chat.pk}"},
    )

    assert_response(response, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert (report.sphere, report.conversation) == (None, chat)
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    staff_view = client.get(
        reverse("admin:db_main_parleyreport_changelist"), {"sphere__isempty": "1"}
    )
    assert list(staff_view.context["cl"].result_list) == [report]


def test_anonymous_report_is_unauthorized(client, sphere):
    sphere.parley_enabled = True
    sphere.save()

    response = client.post(
        reverse("parley_report"),
        data={"message_id": MESSAGE_ID, "room_id": f"organizers:{sphere.pk}"},
    )

    assert_response(
        response,
        HTTPStatus.UNAUTHORIZED,
        content=b'{"error": "authentication_required"}',
    )
    assert not ParleyReport.objects.exists()


@pytest.mark.parametrize(
    ("message_id", "room_id"),
    (("not-a-number", "organizers"), (str(MESSAGE_ID), None)),
    ids=["non-numeric-message", "missing-room"],
)
def test_malformed_report_is_rejected_without_side_effects(
    authenticated_client, sphere, message_id, room_id
):
    sphere.parley_enabled = True
    sphere.save()
    data = {"message_id": message_id}
    if room_id is not None:
        data["room_id"] = f"organizers:{sphere.pk}"

    response = authenticated_client.post(reverse("parley_report"), data=data)

    assert_response(
        response,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        content=b'{"error": "invalid_report"}',
    )
    assert not ParleyReport.objects.exists()
