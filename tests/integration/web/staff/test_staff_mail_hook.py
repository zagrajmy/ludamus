"""The webhook posta forwards staff@ mail to.

What could go wrong, and so what the tests below check:
- an unsigned, altered, replayed or stale message is filed;
- the hook answers while no secret is set, so anyone can post to it;
- a message naming a case opens a new one, or one naming none is dropped;
- a redelivered message is filed twice;
- a message without a sender is filed with nobody to answer.
"""

import time
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.gates.web.django.staff.mail import SIGNATURE_HEADER, signature
from ludamus.links.db.django.models import (
    ParleyConversation,
    ParleyConversationMember,
    StaffCase,
    StaffCaseEmail,
)
from tests.integration.utils import assert_response, assert_response_404

URL = reverse("web:staff-mail")
SECRET = "posta-test-secret"


pytestmark = pytest.mark.usefixtures("_secret")


@pytest.fixture
def _secret(settings):
    settings.STAFF_MAIL_WEBHOOK_SECRET = SECRET


def _mail(
    *,
    subject="Zgłoszenie treści",
    message_id="<abc@mail.example>",
    sender="Ola W. <ola@example.com>",
):
    return (
        f"From: {sender}\r\n"
        "To: staff@zagrajmy.net\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {message_id}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Ktoś prosi mojego brata o telefon.\r\n"
    ).encode()


def _post(client, raw, *, timestamp=None, secret=SECRET):
    stamp = int(time.time()) if timestamp is None else timestamp
    header = f"t={stamp},v1={signature(secret=secret, timestamp=stamp, body=raw)}"
    return client.generic(
        "POST",
        URL,
        raw,
        content_type="message/rfc822",
        headers={SIGNATURE_HEADER: header},
    )


class TestSignature:
    @pytest.mark.parametrize(
        "sent",
        (
            pytest.param({"secret": "wrong"}, id="another key"),
            pytest.param({"timestamp": int(time.time()) - 3_600}, id="an hour old"),
        ),
    )
    def test_refuses_a_bad_or_stale_signature(self, client, sent):
        response = _post(client, _mail(), **sent)

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "Bad signature."}
        )
        assert not StaffCase.objects.exists()

    def test_refuses_a_body_changed_after_signing(self, client):
        stamp = int(time.time())
        header = (
            f"t={stamp},v1={signature(secret=SECRET, timestamp=stamp, body=_mail())}"
        )

        response = client.generic(
            "POST",
            URL,
            _mail(subject="Podmienione"),
            content_type="message/rfc822",
            headers={SIGNATURE_HEADER: header},
        )

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "Bad signature."}
        )
        assert not StaffCase.objects.exists()

    def test_refuses_a_missing_signature(self, client):
        response = client.generic("POST", URL, _mail(), content_type="message/rfc822")

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "Bad signature."}
        )

    def test_is_closed_without_a_secret(self, client, settings):
        settings.STAFF_MAIL_WEBHOOK_SECRET = ""

        response = _post(client, _mail())

        assert_response_404(response)
        assert not StaffCase.objects.exists()


class TestRouting:
    def test_mail_without_a_case_number_opens_a_case_for_staff(
        self, client, staff_user
    ):
        response = _post(client, _mail())

        case = StaffCase.objects.get()
        assert_response(
            response, HTTPStatus.OK, json={"outcome": "opened", "case": f"Z-{case.pk}"}
        )
        assert (case.kind, case.title, case.external_email, case.external_name) == (
            "email",
            "Zgłoszenie treści",
            "ola@example.com",
            "Ola W.",
        )
        assert case.conversation.kind == ParleyConversation.Kind.STAFF
        assert list(
            ParleyConversationMember.objects.filter(
                conversation=case.conversation
            ).values_list("user_id", "state")
        ) == [(staff_user.pk, "active")]
        email = StaffCaseEmail.objects.get()
        assert (email.direction, email.message_id, email.body) == (
            "in",
            "<abc@mail.example>",
            "Ktoś prosi mojego brata o telefon.",
        )

    def test_a_case_number_in_the_subject_files_it_with_that_case(self, client):
        _post(client, _mail())
        case = StaffCase.objects.get()
        StaffCase.objects.filter(pk=case.pk).update(status="waiting")

        response = _post(
            client,
            _mail(subject=f"Re: [Z-{case.pk}] Zgłoszenie", message_id="<reply@x>"),
        )

        assert_response(
            response,
            HTTPStatus.OK,
            json={"outcome": "attached", "case": f"Z-{case.pk}"},
        )
        assert StaffCase.objects.get().status == "open"
        assert list(
            StaffCaseEmail.objects.filter(case=case).values_list(
                "message_id", flat=True
            )
        ) == ["<abc@mail.example>", "<reply@x>"]

    def test_delivered_twice_is_filed_once(self, client):
        first = _post(client, _mail())

        again = _post(client, _mail())

        case = StaffCase.objects.get()
        assert first.json()["outcome"] == "opened"
        assert_response(
            again, HTTPStatus.OK, json={"outcome": "duplicate", "case": f"Z-{case.pk}"}
        )
        assert StaffCaseEmail.objects.count() == 1

    def test_mail_without_a_sender_is_refused(self, client):
        response = _post(client, _mail(sender=""))

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "No sender address."},
        )
        assert not StaffCase.objects.exists()
