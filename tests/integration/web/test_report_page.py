from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.core.cache import cache
from django.urls import reverse

from ludamus.links.db.django.models import ContentNotice, ModerationCase
from ludamus.specs.moderation import NOTICES_PER_ADDRESS
from tests.integration.utils import assert_response

URL = reverse("report")
STAFF_EMAIL = "staff@zagrajmy.net"
REPORTED = "https://zagrajmy.net/event/autumn/?session=4"


@pytest.fixture(name="fresh_throttle")
def fresh_throttle_fixture():
    cache.clear()


pytestmark = pytest.mark.usefixtures("fresh_throttle")


def _notice(**overrides):
    return {
        "url": REPORTED,
        "category": "fraud",
        "explanation": "A fake ticket shop asks for card numbers.",
        "reporter_name": "Ola",
        "reporter_email": "ola@example.com",
        "good_faith": "on",
    } | overrides


def _page(form=ANY, sent_reference=""):
    return {"form": form, "sent_reference": sent_reference, "staff_email": STAFF_EMAIL}


class TestReportPage:
    def test_anyone_gets_the_form_with_the_reported_address_filled_in(self, client):
        response = client.get(URL, {"url": REPORTED})

        assert_response(
            response, HTTPStatus.OK, template_name="report.html", context_data=_page()
        )

    def test_the_sent_state_names_the_case(self, client):
        response = client.get(URL, {"sent": "Z-12"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="report.html",
            context_data=_page(form=None, sent_reference="Z-12"),
        )

    def test_a_forged_sent_reference_shows_the_form(self, client):
        response = client.get(URL, {"sent": "<b>Z-12</b>"})

        assert_response(
            response, HTTPStatus.OK, template_name="report.html", context_data=_page()
        )

    def test_a_notice_opens_a_case_and_mails_staff_and_the_reporter(
        self, client, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(URL, _notice())

        notice = ContentNotice.objects.get()
        reference = f"Z-{notice.case_id}"
        assert_response(response, HTTPStatus.FOUND, url=f"{URL}?sent={reference}")
        assert (
            notice.url,
            notice.category,
            notice.reporter_email,
            notice.reporter_id,
            notice.status,
            notice.language,
        ) == (REPORTED, "fraud", "ola@example.com", None, "open", "en")
        staff, receipt = mailoutbox
        assert (staff.to, staff.subject, staff.extra_headers) == (
            [STAFF_EMAIL],
            f"[{reference}] New notice of illegal content: Fraud, scam or phishing",
            {"Reply-To": STAFF_EMAIL},
        )
        assert staff.body == (
            f"Content: {REPORTED}\n\n"
            "Explanation:\nA fake ticket shop asks for card numbers.\n\n"
            "Decide in the admin:"
            f" https://testserver/admin/db_main/contentnotice/{notice.pk}/change/"
        )
        assert (receipt.to, receipt.subject, receipt.extra_headers) == (
            ["ola@example.com"],
            f"[{reference}] We received your report",
            {"Reply-To": STAFF_EMAIL},
        )
        assert "card numbers" not in receipt.body

    def test_a_signed_in_reporter_is_kept_with_the_notice(
        self, authenticated_client, active_user
    ):
        authenticated_client.post(URL, _notice())

        assert ContentNotice.objects.get().reporter == active_user

    def test_csam_can_be_reported_anonymously_and_stands_out_to_staff(
        self, client, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(
                URL,
                _notice(
                    category="child_sexual_abuse", reporter_name="", reporter_email=""
                ),
            )

        notice = ContentNotice.objects.get()
        (staff,) = mailoutbox
        assert staff.subject == (
            f"[CHILD SAFETY] [Z-{notice.case_id}] New notice of illegal content:"
            " Child sexual abuse material"
        )
        assert "Dyżurnet.pl" in staff.body

    def test_other_categories_need_a_name_and_email(self, client, mailoutbox):
        response = client.post(URL, _notice(reporter_name="", reporter_email=""))

        assert_response(
            response, HTTPStatus.OK, template_name="report.html", context_data=_page()
        )
        assert not ContentNotice.objects.exists()
        assert not ModerationCase.objects.exists()
        assert mailoutbox == []

    def test_a_notice_without_the_good_faith_statement_is_not_taken(self, client):
        response = client.post(URL, _notice(good_faith=""))

        assert_response(
            response, HTTPStatus.OK, template_name="report.html", context_data=_page()
        )
        assert not ContentNotice.objects.exists()

    def test_one_address_sending_too_many_is_asked_to_wait(self, client):
        for _ in range(NOTICES_PER_ADDRESS):
            client.post(URL, _notice(), REMOTE_ADDR="203.0.113.9")

        response = client.post(URL, _notice(), REMOTE_ADDR="203.0.113.9")

        assert_response(
            response, HTTPStatus.OK, template_name="report.html", context_data=_page()
        )
        assert ContentNotice.objects.count() == NOTICES_PER_ADDRESS
