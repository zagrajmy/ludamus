import json
from datetime import UTC, datetime
from http import HTTPStatus

import pytest
import requests
import responses
from django.urls import reverse

from ludamus.links.db.django.models import (
    ParleyConversation,
    ParleyConversationMember,
    ParleyReport,
)
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.parley.helpers import decode_segment

ADULT = AgeBand.SIXTEEN_PLUS.value
LOOKUP = "https://parley.example.com/messages"
MESSAGE_ID = 7
WRITTEN_AT_MS = 1_786_017_600_000


@pytest.fixture(name="me")
def _me(active_user):
    active_user.age_band = ADULT
    active_user.save()
    return active_user


pytestmark = pytest.mark.usefixtures("parley_settings")


def _conversation(*members):
    conversation = ParleyConversation.objects.create(kind="group", title="Crew")
    for user, state in members:
        ParleyConversationMember.objects.create(
            conversation=conversation, user=user, state=state
        )
    return conversation


def _report(client, conversation_id, message_id=MESSAGE_ID):
    return client.post(
        reverse("parley_report"),
        data={
            "good_faith": "1",
            "message_id": message_id,
            "reason": "Abuse",
            "room_id": f"conversation:{conversation_id}",
        },
    )


def _found(author, *, body="You will regret this", deleted_at=None):
    return {
        "authorId": str(author.pk),
        "authorName": author.name,
        "body": body,
        "createdAt": WRITTEN_AT_MS,
        "deletedAt": deleted_at,
    }


@pytest.mark.django_db
@responses.activate
def test_a_member_reports_a_message_and_staff_keep_what_it_said(
    authenticated_client, me
):
    ada = UserFactory(age_band=ADULT, name="Ada")
    conversation = _conversation((me, "active"), (ada, "active"))
    responses.post(
        LOOKUP, json=_found(ada, deleted_at=WRITTEN_AT_MS + 1000), status=200
    )

    response = _report(authenticated_client, conversation.pk)

    assert_response(response, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert (
        report.conversation,
        report.sphere,
        report.reporter,
        report.reported_user,
        report.author_name,
        report.body,
        report.written_at,
    ) == (
        conversation,
        None,
        me,
        ada,
        "Ada",
        "You will regret this",
        datetime.fromtimestamp(WRITTEN_AT_MS / 1000, tz=UTC),
    )
    assert report.deleted_at is not None
    token = json.loads(responses.calls[0].request.body)["token"]
    claims = decode_segment(token.split(".")[1])
    assert (claims["aud"], claims["room"], claims["message"]) == (
        "parley-message",
        f"conversation:{conversation.pk}",
        MESSAGE_ID,
    )


@pytest.mark.django_db
@responses.activate
def test_a_request_can_be_reported_before_it_is_answered(authenticated_client, me):
    stranger = UserFactory(age_band=ADULT, name="Stranger")
    conversation = _conversation((stranger, "active"), (me, "request"))
    responses.post(LOOKUP, json=_found(stranger), status=200)

    response = _report(authenticated_client, conversation.pk)

    assert_response(response, HTTPStatus.CREATED)
    assert ParleyReport.objects.get().reported_user == stranger


@pytest.mark.django_db
@responses.activate
@pytest.mark.parametrize("state", ("left", None), ids=("left", "never-in"))
def test_only_someone_in_the_conversation_reports_from_it(
    authenticated_client, me, state
):
    ada = UserFactory(age_band=ADULT, name="Ada")
    members = [(ada, "active")] + ([(me, state)] if state else [])
    conversation = _conversation(*members)

    response = _report(authenticated_client, conversation.pk)

    assert_response(
        response,
        HTTPStatus.UNPROCESSABLE_CONTENT,
        content=b'{"error": "invalid_report"}',
    )
    assert not ParleyReport.objects.exists()
    assert not responses.calls


@pytest.mark.django_db
@responses.activate
@pytest.mark.usefixtures("me")
def test_a_room_that_is_not_a_conversation_id_is_refused(authenticated_client):
    response = authenticated_client.post(
        reverse("parley_report"),
        data={"good_faith": "1", "message_id": MESSAGE_ID, "room_id": "conversation:x"},
    )

    assert_response(response, HTTPStatus.UNPROCESSABLE_CONTENT)
    assert not ParleyReport.objects.exists()


@pytest.mark.django_db
@responses.activate
@pytest.mark.parametrize("whose", ("nobody", "mine"))
def test_a_message_the_room_lacks_or_ones_own_is_not_reported(
    authenticated_client, me, whose
):
    ada = UserFactory(age_band=ADULT, name="Ada")
    conversation = _conversation((me, "active"), (ada, "active"))
    if whose == "mine":
        responses.post(LOOKUP, json=_found(me), status=200)
    else:
        responses.post(LOOKUP, status=404)

    response = _report(authenticated_client, conversation.pk)

    assert_response(response, HTTPStatus.UNPROCESSABLE_CONTENT)
    assert not ParleyReport.objects.exists()


@pytest.mark.django_db
@responses.activate
@pytest.mark.parametrize("failure", ("error", "unreachable", "garbled"))
def test_a_report_stands_without_its_copy_when_the_worker_cannot_say(
    authenticated_client, me, failure
):
    ada = UserFactory(age_band=ADULT, name="Ada")
    conversation = _conversation((me, "active"), (ada, "active"))
    if failure == "error":
        responses.post(LOOKUP, status=503)
    elif failure == "garbled":
        responses.post(LOOKUP, json={"body": "half a message"}, status=200)
    else:
        responses.post(LOOKUP, body=requests.ConnectionError("down"))

    response = _report(authenticated_client, conversation.pk)

    assert_response(response, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert (report.conversation, report.body, report.reported_user) == (
        conversation,
        "",
        None,
    )


@pytest.mark.django_db
@responses.activate
def test_reporting_the_same_message_again_keeps_one_report(authenticated_client, me):
    ada = UserFactory(age_band=ADULT, name="Ada")
    conversation = _conversation((me, "active"), (ada, "active"))
    responses.post(LOOKUP, json=_found(ada), status=200)

    _report(authenticated_client, conversation.pk)
    response = _report(authenticated_client, conversation.pk)

    assert_response(response, HTTPStatus.CREATED)
    assert ParleyReport.objects.count() == 1
