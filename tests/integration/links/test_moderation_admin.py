from http import HTTPStatus

import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from ludamus.links.db.django import admin as db_admin
from ludamus.links.db.django.models import (
    ContentNotice,
    ModerationCase,
    ParleyReport,
    StatementOfReasons,
    User,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response

NOTICES_URL = reverse("admin:db_main_contentnotice_changelist")
REPORTS_URL = reverse("admin:db_main_parleyreport_changelist")
USERS_URL = reverse("admin:db_main_user_changelist")
STAFF_EMAIL = "staff@zagrajmy.net"
DECISION_TEXT = "The page sold tickets to an event that does not exist."
PROVISION = "art. 286 § 1 Kodeksu karnego"
ILLEGAL = (
    f"the content is illegal under Polish or European Union law, under {PROVISION}"
)
REDRESS = (
    "If you disagree, reply to this email or write to staff@zagrajmy.net and a"
    " person will look at it again. You can also take the matter to a Polish"
    " court, or complain to the Office of Electronic Communications (UKE),"
    " Poland's Digital Services Coordinator: https://www.uke.gov.pl/"
)


@pytest.fixture(name="superuser_client")
def superuser_client_fixture(client):
    client.force_login(
        UserFactory(username="moderator", is_staff=True, is_superuser=True)
    )
    return client


@pytest.fixture(name="author")
def author_fixture():
    return UserFactory(username="author", email="author@example.com")


@pytest.fixture(name="notice")
def notice_fixture():
    return ContentNotice.objects.create(
        case=ModerationCase.objects.create(),
        url="https://zagrajmy.net/event/autumn/",
        category="fraud",
        explanation="A fake ticket shop.",
        reporter_name="Ola",
        reporter_email="ola@example.com",
        language="en",
    )


@pytest.fixture(name="chat_report")
def chat_report_fixture(sphere, author):
    return ParleyReport.objects.create(
        case=ModerationCase.objects.create(),
        sphere=sphere,
        reporter=UserFactory(username="reporter", email="reporter@example.com"),
        reported_user=author,
        room_id=f"sphere:{sphere.pk}",
        message_id=7,
        reason="Insults",
        author_name="Author",
        body="Words",
    )


def _action(action, records, **extra):
    return {
        "action": action,
        helpers.ACTION_CHECKBOX_NAME: [str(record.pk) for record in records],
        **extra,
    }


def _verdict(**extra):
    return {
        "apply": "Close",
        "status": "actioned",
        "decision": "content_removed",
        "ground": "illegal_content",
        "legal_provision": PROVISION,
        "decision_text": DECISION_TEXT,
    } | extra


def _statement_body(*, decision, origin, ground, facts=DECISION_TEXT):
    return "\n\n".join(
        (
            f"Zagrajmy staff decided on {decision}.",
            f"What happened:\n{facts}",
            origin,
            "No automated means were used to find the content or reach this decision.",
            f"Ground: {ground}. Terms of Service: https://testserver/terms-of-service/",
            REDRESS,
        )
    )


class TestDecideNotices:
    def test_first_pass_asks_for_the_decision(self, superuser_client, notice):
        response = superuser_client.post(
            NOTICES_URL, _action("decide_notices", [notice])
        )

        assert_response(response, HTTPStatus.OK)
        notice.refresh_from_db()
        assert notice.status == "open"

    def test_acting_mails_the_reporter_and_explains_to_the_author(
        self,
        superuser_client,
        notice,
        author,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = superuser_client.post(
                NOTICES_URL,
                _action(
                    "decide_notices",
                    [notice],
                    **_verdict(affected_account="AUTHOR@example.com"),
                ),
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=NOTICES_URL,
            messages=[
                (messages.INFO, "Decided 1 notice(s)."),
                (messages.INFO, "Statement of reasons mailed to 1 user(s)."),
            ],
        )
        notice.refresh_from_db()
        assert (
            notice.status,
            notice.decision,
            notice.ground,
            notice.legal_provision,
            notice.decision_text,
            notice.resolved_at is not None,
        ) == (
            "actioned",
            "content_removed",
            "illegal_content",
            PROVISION,
            DECISION_TEXT,
            True,
        )
        statement = StatementOfReasons.objects.get()
        assert (
            statement.case_id,
            statement.user,
            statement.decision,
            statement.from_report,
            statement.automated,
        ) == (notice.case_id, author, "content_removed", True, False)
        reference = f"Z-{notice.case_id}"
        outcome, explanation = mailoutbox
        assert (outcome.to, outcome.subject, outcome.extra_headers) == (
            ["ola@example.com"],
            f"[{reference}] Decision on your report",
            {"Reply-To": STAFF_EMAIL},
        )
        assert outcome.body == "\n\n".join(
            (
                f"We reviewed your report {reference} and acted on the content.",
                f"Why:\n{DECISION_TEXT}",
                REDRESS,
            )
        )
        assert (explanation.to, explanation.subject) == (
            ["author@example.com"],
            f"[{reference}] A moderation decision about your account",
        )
        assert explanation.body == _statement_body(
            decision="removal of your content",
            origin="This decision followed a report from someone else.",
            ground=ILLEGAL,
        )
        assert "Ola" not in explanation.body

    def test_acting_with_nobody_named_warns_that_no_statement_went_out(
        self, superuser_client, notice
    ):
        response = superuser_client.post(
            NOTICES_URL, _action("decide_notices", [notice], **_verdict())
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=NOTICES_URL,
            messages=[
                (messages.INFO, "Decided 1 notice(s)."),
                (
                    messages.WARNING,
                    (
                        "No statement of reasons went out: no affected account was"
                        " named. Send one from Users if someone's content was acted"
                        " on."
                    ),
                ),
            ],
        )
        assert not StatementOfReasons.objects.exists()

    def test_rejecting_tells_only_the_reporter(
        self, superuser_client, notice, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            superuser_client.post(
                NOTICES_URL,
                _action(
                    "decide_notices",
                    [notice],
                    **_verdict(
                        status="rejected", decision="", ground="", legal_provision=""
                    ),
                ),
            )

        notice.refresh_from_db()
        assert (notice.status, notice.decision) == ("rejected", "no_action")
        (outcome,) = mailoutbox
        assert outcome.body.startswith(
            f"We reviewed your report Z-{notice.case_id} and decided not to act"
        )
        assert not StatementOfReasons.objects.exists()

    @pytest.mark.parametrize(
        "extra",
        (
            {"affected_account": "nobody"},
            {"affected_account": "shared@example.com"},
            {"ground": ""},
            {"legal_provision": ""},
            {"decision": "account_suspended", "ground": "terms_4_1_6"},
        ),
        ids=[
            "unknown-account",
            "ambiguous-account",
            "no-ground",
            "law-without-provision",
            "suspension-without-end",
        ],
    )
    def test_a_decision_that_does_not_hold_changes_nothing(
        self, superuser_client, notice, mailoutbox, extra
    ):
        UserFactory(username="shared@example.com", email="first@example.com")
        UserFactory(username="second", email="shared@example.com")

        response = superuser_client.post(
            NOTICES_URL, _action("decide_notices", [notice], **_verdict(**extra))
        )

        assert_response(response, HTTPStatus.OK)
        notice.refresh_from_db()
        assert notice.status == "open"
        assert mailoutbox == []

    def test_one_account_cannot_be_named_for_several_notices(
        self, superuser_client, notice, author, mailoutbox
    ):
        other = ContentNotice.objects.create(
            case=ModerationCase.objects.create(),
            url="https://zagrajmy.net/event/winter/",
            category="fraud",
            explanation="Another shop.",
            language="en",
        )

        response = superuser_client.post(
            NOTICES_URL,
            _action(
                "decide_notices", [notice, other], **_verdict(affected_account="author")
            ),
        )

        assert_response(response, HTTPStatus.OK)
        assert set(ContentNotice.objects.values_list("status", flat=True)) == {"open"}
        assert mailoutbox == []

    def test_a_notice_is_read_only(self, superuser_client, notice):
        response = superuser_client.post(
            reverse("admin:db_main_contentnotice_change", args=[notice.pk]),
            {"status": "actioned"},
        )

        assert_response(response, HTTPStatus.FORBIDDEN)
        notice.refresh_from_db()
        assert notice.status == "open"

    def test_without_registered_services_the_admin_says_so(
        self, superuser_client, notice, monkeypatch
    ):
        monkeypatch.setattr(db_admin._wiring, "services", None)

        with pytest.raises(ImproperlyConfigured):
            superuser_client.post(
                NOTICES_URL, _action("decide_notices", [notice], **_verdict())
            )


class TestDecideChatReports:
    def test_acting_mails_the_reporter_and_explains_to_the_author(
        self,
        superuser_client,
        chat_report,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = superuser_client.post(
                REPORTS_URL,
                _action(
                    "decide_chat_reports",
                    [chat_report],
                    **_verdict(
                        decision="warning", ground="terms_4_1_6", legal_provision=""
                    ),
                ),
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (messages.INFO, "Decided 1 chat report(s)."),
                (messages.INFO, "Statement of reasons mailed to 1 user(s)."),
            ],
        )
        chat_report.refresh_from_db()
        assert (chat_report.status, chat_report.resolved_at is not None) == (
            "actioned",
            True,
        )
        outcome, explanation = mailoutbox
        assert (outcome.to, explanation.to) == (
            ["reporter@example.com"],
            ["author@example.com"],
        )
        assert explanation.body == _statement_body(
            decision="a warning",
            origin="This decision followed a report from someone else.",
            ground="§ 4.1(6) of the Terms of Service: violating other users' rights",
        )

    def test_first_pass_asks_for_the_decision(self, superuser_client, chat_report):
        response = superuser_client.post(
            REPORTS_URL, _action("decide_chat_reports", [chat_report])
        )

        assert_response(response, HTTPStatus.OK)

    def test_an_incoherent_decision_changes_nothing(
        self, superuser_client, chat_report, mailoutbox
    ):
        response = superuser_client.post(
            REPORTS_URL,
            _action("decide_chat_reports", [chat_report], **_verdict(decision="")),
        )

        assert_response(response, HTTPStatus.OK)
        chat_report.refresh_from_db()
        assert chat_report.status == "open"
        assert mailoutbox == []

    def test_an_unproven_address_still_gets_the_statement_but_not_the_outcome(
        self,
        superuser_client,
        chat_report,
        author,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        User.objects.filter(pk__in=[author.pk, chat_report.reporter_id]).update(
            email_verified=False
        )

        with django_capture_on_commit_callbacks(execute=True):
            superuser_client.post(
                REPORTS_URL, _action("decide_chat_reports", [chat_report], **_verdict())
            )

        assert [mail.to for mail in mailoutbox] == [["author@example.com"]]
        assert StatementOfReasons.objects.get().user == author

    def test_an_author_with_no_address_is_named_for_staff_to_reach(
        self, superuser_client, chat_report, author, mailoutbox
    ):
        User.objects.filter(pk=author.pk).update(email="")

        response = superuser_client.post(
            REPORTS_URL, _action("decide_chat_reports", [chat_report], **_verdict())
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=REPORTS_URL,
            messages=[
                (messages.INFO, "Decided 1 chat report(s)."),
                (
                    messages.WARNING,
                    f"No address on record for {author.name}: reach them another way.",
                ),
            ],
        )
        assert StatementOfReasons.objects.get().user == author

    def test_everyone_who_reported_a_message_hears_back_and_its_author_once(
        self,
        superuser_client,
        chat_report,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        second = ParleyReport.objects.create(
            case=chat_report.case,
            sphere=chat_report.sphere,
            reporter=UserFactory(username="second", email="second@example.com"),
            reported_user=chat_report.reported_user,
            room_id=chat_report.room_id,
            message_id=chat_report.message_id,
        )

        with django_capture_on_commit_callbacks(execute=True):
            superuser_client.post(
                REPORTS_URL,
                _action("decide_chat_reports", [chat_report, second], **_verdict()),
            )

        assert sorted(mail.to[0] for mail in mailoutbox) == [
            "author@example.com",
            "reporter@example.com",
            "second@example.com",
        ]
        assert StatementOfReasons.objects.count() == 1


class TestSendStatementOfReasons:
    def test_first_pass_asks_for_the_statement(self, superuser_client, author):
        response = superuser_client.post(
            USERS_URL, _action("send_statement_of_reasons", [author])
        )

        assert_response(response, HTTPStatus.OK)
        assert not StatementOfReasons.objects.exists()

    def test_staff_acting_on_their_own_explain_it_under_a_new_case(
        self, superuser_client, author, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = superuser_client.post(
                USERS_URL,
                _action(
                    "send_statement_of_reasons",
                    [author],
                    apply="Send",
                    decision="account_suspended",
                    ground="terms_4_1_2",
                    suspended_until="2026-12-31",
                    facts="Three accounts enrolled in one seat.",
                ),
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=USERS_URL,
            messages=[(messages.INFO, "Statement of reasons mailed to 1 user(s).")],
        )
        statement = StatementOfReasons.objects.get()
        assert (statement.user, statement.from_report, statement.case_id) == (
            author,
            False,
            ModerationCase.objects.get().pk,
        )
        (mail,) = mailoutbox
        assert mail.subject == (
            f"[Z-{statement.case_id}] A moderation decision about your account"
        )
        assert mail.body == _statement_body(
            decision="suspension of your account until Dec. 31, 2026",
            origin="We took this decision on our own initiative.",
            ground=("§ 4.1(2) of the Terms of Service: creating more than one account"),
            facts="Three accounts enrolled in one seat.",
        )

    def test_a_suspension_without_its_end_sends_nothing(
        self, superuser_client, author, mailoutbox
    ):
        response = superuser_client.post(
            USERS_URL,
            _action(
                "send_statement_of_reasons",
                [author],
                apply="Send",
                decision="account_suspended",
                ground="terms_4_1_2",
                facts="Three accounts enrolled in one seat.",
            ),
        )

        assert_response(response, HTTPStatus.OK)
        assert not StatementOfReasons.objects.exists()
        assert mailoutbox == []
