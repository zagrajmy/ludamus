"""The webhook posta forwards staff@ mail to.

What could go wrong, and so what the tests below check:
- an unsigned, altered, replayed or stale message is filed;
- the hook answers while no secret is set, so anyone can post to it;
- a message naming a case opens a new one, or one naming none is dropped;
- a redelivered message is filed twice;
- a message without a sender is filed with nobody to answer;
- an HTML-only message is filed with its markup, an attachment-only one or one
  without a Message-ID is dropped, an oversized one breaks the hook, and
  headers longer than a case keeps break filing it; a charset Python lacks
  or a From that is no address files an unanswerable case or a 500.
"""

import time
from email.message import EmailMessage
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.gates.web.django.staff.mail import SIGNATURE_HEADER, signature
from ludamus.links.db.django.models import (
    CaseEmail,
    ModerationCase,
    ParleyConversation,
    ParleyConversationMember,
)
from ludamus.pacts.staff_cases import CASE_EMAIL_LINE_MAX_LENGTH
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
        assert not ModerationCase.objects.exists()

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
        assert not ModerationCase.objects.exists()

    def test_refuses_a_signature_without_a_time(self, client):
        response = client.generic(
            "POST",
            URL,
            _mail(),
            content_type="message/rfc822",
            headers={SIGNATURE_HEADER: "t=soon,v1=abc"},
        )

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "Bad signature."}
        )

    def test_refuses_a_message_over_the_upload_limit(self, client, settings):
        settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 10

        response = _post(client, _mail())

        assert_response(
            response,
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            json={"error": "Message too large."},
        )
        assert not ModerationCase.objects.exists()

    def test_refuses_a_missing_signature(self, client):
        response = client.generic("POST", URL, _mail(), content_type="message/rfc822")

        assert_response(
            response, HTTPStatus.UNAUTHORIZED, json={"error": "Bad signature."}
        )

    def test_is_closed_without_a_secret(self, client, settings):
        settings.STAFF_MAIL_WEBHOOK_SECRET = ""

        response = _post(client, _mail())

        assert_response_404(response)
        assert not ModerationCase.objects.exists()


class TestRouting:
    def test_mail_without_a_case_number_opens_a_case_for_staff(
        self, client, staff_user
    ):
        response = _post(client, _mail())

        case = ModerationCase.objects.get()
        assert_response(
            response, HTTPStatus.OK, json={"outcome": "opened", "case": f"Z-{case.pk}"}
        )
        assert (case.thread.kind, case.thread.title) == (
            ParleyConversation.Kind.STAFF,
            f"Z-{case.pk}",
        )
        assert list(
            ParleyConversationMember.objects.filter(
                conversation=case.thread
            ).values_list("user_id", "state")
        ) == [(staff_user.pk, "active")]
        email = CaseEmail.objects.get()
        assert (email.direction, email.message_id, email.body) == (
            "in",
            "<abc@mail.example>",
            "Ktoś prosi mojego brata o telefon.",
        )
        assert (email.address, email.name, email.subject) == (
            "ola@example.com",
            "Ola W.",
            "Zgłoszenie treści",
        )

    def test_a_case_number_in_the_subject_files_it_with_that_case(self, client):
        _post(client, _mail())
        case = ModerationCase.objects.get()
        ModerationCase.objects.filter(pk=case.pk).update(status="waiting")

        response = _post(
            client,
            _mail(subject=f"Re: [Z-{case.pk}] Zgłoszenie", message_id="<reply@x>"),
        )

        assert_response(
            response,
            HTTPStatus.OK,
            json={"outcome": "attached", "case": f"Z-{case.pk}"},
        )
        assert ModerationCase.objects.get().status == "open"
        assert list(
            CaseEmail.objects.filter(case=case).values_list("message_id", flat=True)
        ) == ["<abc@mail.example>", "<reply@x>"]

    def test_delivered_twice_is_filed_once(self, client):
        first = _post(client, _mail())

        again = _post(client, _mail())

        case = ModerationCase.objects.get()
        assert first.json()["outcome"] == "opened"
        assert_response(
            again, HTTPStatus.OK, json={"outcome": "duplicate", "case": f"Z-{case.pk}"}
        )
        assert CaseEmail.objects.count() == 1

    def test_mail_without_a_sender_is_refused(self, client):
        response = _post(client, _mail(sender=""))

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "No sender address."},
        )
        assert not ModerationCase.objects.exists()


class TestParsing:
    def test_reads_an_html_only_message_as_text_and_names_its_attachments(self, client):
        message = EmailMessage()
        message["From"] = "ola@example.com"
        message["Subject"] = "Zrzut"
        message.set_content("<p>Patrz <b>zrzut</b>.</p>", subtype="html")
        message.add_attachment(
            b"%PDF", maintype="application", subtype="pdf", filename="zrzut.pdf"
        )

        _post(client, message.as_bytes())

        email = CaseEmail.objects.get()
        assert (email.body, email.attachments, email.message_id[-7:]) == (
            "Patrz zrzut.",
            ["zrzut.pdf"],
            "@posta>",
        )

    def test_files_an_attachment_with_no_text_at_all(self, client):
        message = EmailMessage()
        message["From"] = "ola@example.com"
        message["Message-ID"] = "<only-file@mail.example>"
        message.add_attachment(b"\x89PNG", maintype="image", subtype="png")

        _post(client, message.as_bytes())

        email = CaseEmail.objects.get()
        assert (email.body, email.attachments, email.subject) == ("", ["image/png"], "")

    def test_files_overlong_headers_clipped_to_what_a_case_keeps(self, client):
        raw = _mail(
            subject="s" * 600,
            message_id=f"<{'m' * 300}@mail.example>",
            sender=f"{'n' * 400} <ola@example.com>",
        )

        _post(client, raw)

        email = CaseEmail.objects.get()
        assert (len(email.subject), len(email.name), email.message_id[-7:]) == (
            CASE_EMAIL_LINE_MAX_LENGTH,
            CASE_EMAIL_LINE_MAX_LENGTH,
            "@posta>",
        )

    def test_reads_a_charset_python_lacks_instead_of_failing(self, client):
        raw = (
            b"From: ola@example.com\r\nSubject: Zrzut\r\n"
            b"Message-ID: <odd@mail.example>\r\n"
            b"Content-Type: text/plain; charset=unknown-8bit\r\n\r\n"
            b"Prosz\xc4\x99 spojrze\xc4\x87.\r\n"
        )

        response = _post(client, raw)

        assert response.status_code == HTTPStatus.OK
        assert CaseEmail.objects.get().body == "Proszę spojrzeć."

    @pytest.mark.parametrize(
        "sender",
        (
            pytest.param("not an address", id="no address"),
            pytest.param(f"{'a' * 250}@example.com", id="too long to keep"),
        ),
    )
    def test_refuses_a_sender_it_could_not_answer(self, client, sender):
        response = _post(client, _mail(sender=sender))

        assert_response(
            response,
            HTTPStatus.UNPROCESSABLE_ENTITY,
            json={"error": "No sender address."},
        )
        assert not CaseEmail.objects.exists()
