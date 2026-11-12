from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import (
    ParleyConversationMember,
    ParleyReport,
    StaffCase,
)
from ludamus.pacts.user import AgeBand
from tests.integration.utils import assert_response

MESSAGE_ID = 42


@pytest.fixture(name="organizer")
def organizer_fixture(active_user, sphere):
    sphere.managers.add(active_user)
    return active_user


def _report(client, sphere, *, reason="Spam"):
    return client.post(
        reverse("parley_report"),
        data={
            "message_id": MESSAGE_ID,
            "reason": reason,
            "room_id": f"organizers:{sphere.pk}",
        },
    )


def test_a_chat_report_opens_a_case_with_staff_on_its_thread(
    authenticated_client, organizer, sphere, staff_user
):
    response = _report(authenticated_client, sphere)

    assert_response(response, HTTPStatus.CREATED)
    case = StaffCase.objects.get()
    assert (case.kind, case.report, case.title, case.child_safety) == (
        "chat_report",
        ParleyReport.objects.get(),
        "Spam",
        False,
    )
    assert (case.external_email, case.external_name) == (
        organizer.email,
        organizer.get_full_name(),
    )
    assert list(
        ParleyConversationMember.objects.filter(
            conversation=case.conversation
        ).values_list("user_id", flat=True)
    ) == [staff_user.pk]


def test_a_report_by_a_teen_is_a_child_safety_case(
    authenticated_client, organizer, sphere
):
    organizer.age_band = AgeBand.THIRTEEN_TO_FIFTEEN
    organizer.save()

    _report(authenticated_client, sphere)

    assert StaffCase.objects.get().child_safety is True


@pytest.mark.usefixtures("organizer")
def test_reporting_again_keeps_one_case(authenticated_client, sphere):
    _report(authenticated_client, sphere)

    _report(authenticated_client, sphere, reason="Again")

    assert StaffCase.objects.count() == 1
