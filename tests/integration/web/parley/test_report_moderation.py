from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import ParleyReport
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

MESSAGE_ID = 42


@pytest.fixture(name="chat_sphere")
def chat_sphere_fixture(sphere):
    sphere.parley_enabled = True
    sphere.save()
    return sphere


def _report(client, sphere, **extra):
    return client.post(
        reverse("parley_report"),
        data={
            "message_id": MESSAGE_ID,
            "reason": "Insults",
            "room_id": f"sphere:{sphere.pk}",
        }
        | extra,
    )


def test_a_report_without_the_good_faith_statement_is_refused(
    authenticated_client, chat_sphere, mailoutbox
):
    response = _report(authenticated_client, chat_sphere)

    assert_response(
        response,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        content=b'{"error": "invalid_report"}',
    )
    assert not ParleyReport.objects.exists()
    assert mailoutbox == []


def test_a_report_opens_a_case_and_tells_staff_once(
    authenticated_client, chat_sphere, mailoutbox, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        first = _report(authenticated_client, chat_sphere, good_faith="1")
        again = _report(authenticated_client, chat_sphere, good_faith="1")

    assert_response(first, HTTPStatus.CREATED)
    assert_response(again, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert report.case_id is not None
    (alert,) = mailoutbox
    assert (alert.to, alert.subject) == (
        ["staff@zagrajmy.net"],
        f"[Z-{report.case_id}] New chat report",
    )
    assert alert.body == (
        f"Chat room: sphere:{chat_sphere.pk}\n\n"
        "Explanation:\nInsults\n\n"
        "Decide in the admin:"
        f" https://testserver/admin/db_main/parleyreport/{report.pk}/change/"
    )


def test_a_second_reporter_joins_the_message_case_without_a_second_alert(
    client,
    authenticated_client,
    chat_sphere,
    mailoutbox,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        _report(authenticated_client, chat_sphere, good_faith="1")
        client.force_login(UserFactory())
        _report(client, chat_sphere, good_faith="1")

    first, second = ParleyReport.objects.order_by("pk")
    assert second.case_id == first.case_id
    assert len(mailoutbox) == 1
