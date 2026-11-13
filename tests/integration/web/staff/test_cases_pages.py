"""The staff inbox pages and their actions.

What could go wrong, and so what the tests below check:
- anyone off staff, or signed out, reaches a case or changes one;
- the pages show another case's records or the wrong state's cases;
- a reply by email leaves from the wrong address, without the case number, or
  to someone other than who wrote in; a note leaves the team;
- deciding in the inbox does less than the admin: the chat message stays, the
  reporter hears nothing, the author gets no statement; or it decides after
  the chat failed to remove the message, or on a verdict that does not hold;
- a case is closed with its reports undecided, or handed to someone off staff.
"""

import json
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

import pytest
import responses
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.pages import CONTENT_DIR
from ludamus.links.db.django.models import (
    CaseEmail,
    ContentNotice,
    ModerationCase,
    ParleyReport,
    StatementOfReasons,
)
from ludamus.pacts.moderation import (
    CaseStatus,
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    NoticeCategory,
)
from ludamus.pacts.staff_cases import (
    CaseChatReportDTO,
    CaseDetailDTO,
    CaseDTO,
    CaseEmailDirection,
    CaseEmailDTO,
    CaseKind,
    CaseNoticeDTO,
    CaseVerdictDTO,
    InboxCaseDTO,
    StaffMemberDTO,
)
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import SphereFactory, UserFactory
from tests.integration.utils import PageMatcher, assert_response, assert_response_404
from tests.integration.web.parley.helpers import configure_parley, decode_segment

CASES = reverse("web:staff:cases")
FAQ = (CONTENT_DIR / "moderation-faq.md").read_text(encoding="utf-8")
WORKER = "https://parley.example.com"
DECISION_TEXT = "The message asked a child for their phone number."
DEFAULT_PREVIEW = (
    "Zagrajmy staff decided on removal of your content.\n\n"
    "What happened:\n\n\n"
    "This decision followed a report from someone else.\n\n"
    "No automated means were used to find the content or reach this decision.\n\n"
    "Ground: § 4.1(7) of the Terms of Service: posting content that is unlawful"
    " or offends common decency. Terms of Service:"
    " https://testserver/terms-of-service/\n\n"
    "If you disagree, reply to this email or write to staff@zagrajmy.net and a"
    " person will look at it again. You can also take the matter to a Polish"
    " court, or complain to the Office of Electronic Communications (UKE),"
    " Poland's Digital Services Coordinator: https://www.uke.gov.pl/"
)


@pytest.fixture(name="notice_case")
def notice_case_fixture():
    case = ModerationCase.objects.create()
    ContentNotice.objects.create(
        case=case,
        url="https://zagrajmy.net/e/abc/",
        category=NoticeCategory.HARASSMENT,
        explanation="Offensive description",
        reporter_name="Ola W.",
        reporter_email="ola@example.com",
        language="en",
    )
    return case


@pytest.fixture(name="chat_case")
def chat_case_fixture():
    case = ModerationCase.objects.create()
    sphere = SphereFactory()
    ParleyReport.objects.create(
        case=case,
        sphere=sphere,
        reporter=UserFactory(email="reporter@example.com"),
        reported_user=UserFactory(email="author@example.com"),
        room_id=f"organizers:{sphere.pk}",
        message_id=7,
        reason="Asks for a phone number",
        author_name="Marek",
        body="give me your number",
    )
    return case


def _url(name, case):
    return reverse(f"web:staff:{name}", kwargs={"pk": case.pk})


def _inbox(*, active="open", open_=0, waiting=0, closed=0):
    counts = {"open": open_, "waiting": waiting, "closed": closed}
    icons = {"open": "inbox", "waiting": "clock", "closed": "check-circle"}
    labels = {"open": "Open", "waiting": "Waiting", "closed": "Closed"}
    return {
        "tabs": [
            {
                "key": key,
                "icon": icons[key],
                "label": labels[key],
                "count": counts[key],
                "active": key == active,
            }
            for key in ("open", "waiting", "closed")
        ],
        "faq": FAQ,
        "page_obj": PageMatcher(number=1, num_pages=1),
        "page_sizes": [10, 20, 50, 100],
    }


def _notice_row(case):
    return InboxCaseDTO(
        pk=case.pk,
        kind=CaseKind.NOTICE,
        status=CaseStatus.OPEN,
        title="Offensive description",
        child_safety=False,
        assignee_name="",
        created_at=case.created_at,
    )


def _notice_detail(case, staff_user):
    case.refresh_from_db()
    notice = case.notices.get()
    return CaseDetailDTO(
        case=CaseDTO(
            pk=case.pk,
            kind=CaseKind.NOTICE,
            status=CaseStatus.OPEN,
            title="Offensive description",
            child_safety=False,
            assignee_name="",
            assignee_id=None,
            decided_by_name="",
            thread_id=case.thread_id,
            reply_to="ola@example.com",
            reply_name="Ola W.",
            notices=[
                CaseNoticeDTO(
                    pk=notice.pk,
                    url="https://zagrajmy.net/e/abc/",
                    category=NoticeCategory.HARASSMENT,
                    explanation="Offensive description",
                    reporter_name="Ola W.",
                    status=ModerationStatus.OPEN,
                )
            ],
            chat_reports=[],
            verdict=None,
            created_at=case.created_at,
        ),
        emails=[],
        staff=[StaffMemberDTO(pk=staff_user.pk, name=staff_user.get_full_name())],
        decidable=True,
    )


def _case_page(case, staff_user, *, statement=DEFAULT_PREVIEW):
    return {
        **_inbox(open_=1),
        "detail": _notice_detail(case, staff_user),
        "reply_form": ANY,
        "assign_form": ANY,
        "decision_form": ANY,
        "statement": statement,
    }


def _tokens(worker, path):
    return [
        decode_segment(json.loads(call.request.body)["token"].split(".")[1])
        for call in worker.calls
        if call.request.url == f"{WORKER}{path}"
    ]


def _decide(client, case, **fields):
    return client.post(
        _url("decide", case),
        {"decision": "content_removed", "ground": "terms_4_1_7"}
        | {"decision_text": DECISION_TEXT}
        | fields,
    )


class TestStaffOnly:
    @pytest.mark.parametrize(
        "name", ("case", "reply", "assign", "close", "decide"), ids=str
    )
    def test_someone_off_staff_gets_a_404_and_changes_nothing(
        self, authenticated_client, notice_case, name
    ):
        send = authenticated_client.get if name == "case" else authenticated_client.post

        response = send(
            _url(name, notice_case),
            {"body": "Hi", "send": "email", "decision": "no_action"}
            | {"decision_text": "x"},
        )

        assert_response_404(response)
        notice_case.refresh_from_db()
        assert (notice_case.status, notice_case.thread_id) == ("open", None)
        assert not CaseEmail.objects.exists()

    def test_the_inbox_is_a_404_signed_out(self, client):
        assert_response_404(client.get(CASES))

    def test_the_inbox_is_a_404_off_staff(self, authenticated_client):
        assert_response_404(authenticated_client.get(CASES))

    def test_an_unknown_case_is_a_404(self, staff_client):
        assert_response_404(staff_client.get(reverse("web:staff:case", args=[404])))


class TestInboxPage:
    def test_staff_see_open_cases_and_the_count_of_each_state(
        self, staff_client, notice_case
    ):
        ModerationCase.objects.create(status="closed")

        response = staff_client.get(CASES)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data={**_inbox(open_=1, closed=1), "detail": None},
        )
        assert list(response.context_data["page_obj"]) == [_notice_row(notice_case)]

    def test_an_unknown_state_shows_the_open_cases(self, staff_client):
        response = staff_client.get(CASES, {"status": "lost"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data={**_inbox(), "detail": None},
        )


class TestCasePage:
    def test_opens_the_case_thread_for_staff_and_says_what_the_case_is(
        self,
        staff_client,
        staff_user,
        notice_case,
        settings,
        django_capture_on_commit_callbacks,
    ):
        configure_parley(settings)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as worker:
            worker.post(f"{WORKER}/conversations", status=204)
            worker.post(f"{WORKER}/conversations/messages", status=204)
            with django_capture_on_commit_callbacks(execute=True):
                response = staff_client.get(_url("case", notice_case))
            posts = _tokens(worker, "/conversations/messages")
            (members,) = _tokens(worker, "/conversations")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user),
        )
        (opened,) = posts
        assert (opened["author"], opened["name"], opened["body"]) == (
            "system",
            "Notice of illegal content",
            f"Case Z-{notice_case.pk} opened: Offensive description",
        )
        assert (members["kind"], members["retainFor"], members["members"]) == (
            "staff",
            3 * 365 * 86_400,
            [{"user": str(staff_user.pk), "state": "active", "writable": True}],
        )

    def test_a_chat_that_does_not_answer_leaves_the_page_as_it_is(
        self,
        staff_client,
        staff_user,
        notice_case,
        settings,
        caplog,
        django_capture_on_commit_callbacks,
    ):
        configure_parley(settings)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as worker:
            worker.post(f"{WORKER}/conversations", status=503)
            worker.post(f"{WORKER}/conversations/messages", status=503)
            with django_capture_on_commit_callbacks(execute=True):
                response = staff_client.get(_url("case", notice_case))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user),
        )
        assert "staff thread post failed" in caplog.text

    def test_previews_the_statement_the_author_would_get(
        self, staff_client, staff_user, notice_case
    ):
        response = staff_client.get(
            _url("case", notice_case),
            {
                "decision": "account_suspended",
                "ground": "illegal_content",
                "legal_provision": "art. 190 § 1 k.k.",
                "suspended_until": "2026-12-01",
                "decision_text": "Threats.",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(
                notice_case,
                staff_user,
                statement=(
                    "Zagrajmy staff decided on suspension of your account until"
                    " Dec. 1, 2026.\n\nWhat happened:\nThreats.\n\n"
                    "This decision followed a report from someone else.\n\n"
                    "No automated means were used to find the content or reach"
                    " this decision.\n\n"
                    "Ground: the content is illegal under Polish or European Union"
                    " law, under art. 190 § 1 k.k.. Terms of Service:"
                    " https://testserver/terms-of-service/\n\n"
                    + DEFAULT_PREVIEW.rsplit("\n\n", maxsplit=1)[-1]
                ),
            ),
        )

    def test_no_action_previews_no_statement(
        self, staff_client, staff_user, notice_case
    ):
        response = staff_client.get(
            _url("case", notice_case),
            {"decision": "no_action", "decision_text": "Nothing wrong."},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user, statement=""),
        )


class TestDecidedCase:
    def test_shows_a_decided_chat_case_with_its_mail_child_safety_first(
        self, staff_client, staff_user
    ):
        teen = UserFactory(
            age_band=AgeBand.THIRTEEN_TO_FIFTEEN, email="teen@example.com"
        )
        case = ModerationCase.objects.create(
            status="closed", assignee=staff_user, decided_by=staff_user
        )
        sphere = SphereFactory()
        report = ParleyReport.objects.create(
            case=case,
            sphere=sphere,
            reporter=UserFactory(email="reporter@example.com"),
            reported_user=teen,
            room_id=f"organizers:{sphere.pk}",
            message_id=7,
            reason="Spam",
            author_name="Teen",
            body="buy now",
            written_at=datetime(2026, 11, 12, 14, 0, tzinfo=UTC),
            status="actioned",
            decision="content_removed",
            ground="terms_4_1_5",
            decision_text="Removed.",
        )
        StatementOfReasons.objects.create(
            case=case,
            user=teen,
            decision="content_removed",
            ground="terms_4_1_5",
            facts="Removed.",
            from_report=True,
        )
        appeal = CaseEmail.objects.create(
            case=case,
            direction="in",
            message_id="<appeal@x>",
            address="teen@example.com",
            name="Teen",
            subject=f"Re: [Z-{case.pk}]",
            body="It was a joke.",
            attachments=["shot.png"],
        )
        answer = CaseEmail.objects.create(
            case=case,
            direction="out",
            message_id="answer",
            address="teen@example.com",
            subject=f"[Z-{case.pk}] Spam",
            body="We looked again.",
            sent_by=staff_user,
        )
        staff_name = staff_user.get_full_name()

        response = staff_client.get(_url("case", case))

        case.refresh_from_db()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data={
                **_inbox(active="closed", closed=1),
                "detail": CaseDetailDTO(
                    case=CaseDTO(
                        pk=case.pk,
                        kind=CaseKind.CHAT_REPORT,
                        status=CaseStatus.CLOSED,
                        title="Spam",
                        child_safety=True,
                        assignee_name=staff_name,
                        assignee_id=staff_user.pk,
                        decided_by_name=staff_name,
                        thread_id=case.thread_id,
                        reply_to="teen@example.com",
                        reply_name="Teen",
                        notices=[],
                        chat_reports=[
                            CaseChatReportDTO(
                                pk=report.pk,
                                room_id=f"organizers:{sphere.pk}",
                                reason="Spam",
                                reporter_name=report.reporter.get_full_name(),
                                author_name="Teen",
                                author_age_band=AgeBand.THIRTEEN_TO_FIFTEEN,
                                author_joined_at=teen.date_joined,
                                body="buy now",
                                written_at=datetime(2026, 11, 12, 14, 0, tzinfo=UTC),
                                status=ModerationStatus.ACTIONED,
                            )
                        ],
                        verdict=CaseVerdictDTO(
                            status=ModerationStatus.ACTIONED,
                            decision=ModerationDecision.CONTENT_REMOVED,
                            ground=ModerationGround.TERMS_MISUSE,
                            decision_text="Removed.",
                        ),
                        created_at=case.created_at,
                    ),
                    emails=[
                        CaseEmailDTO(
                            direction=CaseEmailDirection.IN,
                            address="teen@example.com",
                            name="Teen",
                            subject=appeal.subject,
                            body="It was a joke.",
                            attachments=["shot.png"],
                            sent_by_name="",
                            created_at=appeal.created_at,
                        ),
                        CaseEmailDTO(
                            direction=CaseEmailDirection.OUT,
                            address="teen@example.com",
                            name="",
                            subject=answer.subject,
                            body="We looked again.",
                            attachments=[],
                            sent_by_name=staff_name,
                            created_at=answer.created_at,
                        ),
                    ],
                    staff=[StaffMemberDTO(pk=staff_user.pk, name=staff_name)],
                    decidable=False,
                ),
                "reply_form": ANY,
                "assign_form": ANY,
                "decision_form": ANY,
                "statement": DEFAULT_PREVIEW,
            },
        )
        assert list(response.context_data["page_obj"]) == [
            InboxCaseDTO(
                pk=case.pk,
                kind=CaseKind.CHAT_REPORT,
                status=CaseStatus.CLOSED,
                title="Spam",
                child_safety=True,
                assignee_name=staff_name,
                created_at=case.created_at,
            )
        ]


class TestReply:
    def test_by_email_goes_from_staff_with_the_case_number(
        self,
        staff_client,
        staff_user,
        notice_case,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = staff_client.post(
                _url("reply", notice_case), {"body": "Thank you.", "send": "email"}
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.SUCCESS, "Reply sent.")],
        )
        (mail,) = mailoutbox
        assert (mail.to, mail.from_email, mail.subject, mail.body) == (
            ["ola@example.com"],
            "staff@zagrajmy.net",
            f"[Z-{notice_case.pk}] Offensive description",
            "Thank you.",
        )
        sent = CaseEmail.objects.get(direction="out")
        assert mail.extra_headers["Message-ID"] == (
            f"<case-{sent.message_id}@zagrajmy.net>"
        )
        assert sent.sent_by == staff_user
        notice_case.refresh_from_db()
        assert notice_case.status == "waiting"

    def test_a_note_stays_inside(
        self, staff_client, notice_case, mailoutbox, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = staff_client.post(
                _url("reply", notice_case), {"body": "Checking", "send": "note"}
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.SUCCESS, "Note added to the thread.")],
        )
        assert mailoutbox == []
        assert not CaseEmail.objects.exists()

    def test_an_empty_reply_shows_the_form_again(
        self, staff_client, staff_user, notice_case
    ):
        response = staff_client.post(
            _url("reply", notice_case), {"body": "", "send": "email"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user),
        )
        form = response.context_data["reply_form"]
        assert form.errors == {"body": ["This field is required."]}

    def test_by_email_with_nobody_to_answer_is_refused(self, staff_client):
        case = ModerationCase.objects.create()

        response = staff_client.post(
            _url("reply", case), {"body": "Hi", "send": "email"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", case),
            messages=[
                (
                    messages.ERROR,
                    "Nobody outside the team wrote in this case. Add a note instead.",
                )
            ],
        )
        assert not CaseEmail.objects.exists()


class TestAssignAndClose:
    def test_hands_the_case_to_someone_on_staff(self, staff_client, notice_case):
        other = UserFactory(is_staff=True)

        response = staff_client.post(
            _url("assign", notice_case), {"assignee": other.pk}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.SUCCESS, "Case assigned.")],
        )
        notice_case.refresh_from_db()
        assert notice_case.assignee == other

    def test_refuses_someone_off_staff(self, staff_client, notice_case, active_user):
        response = staff_client.post(
            _url("assign", notice_case), {"assignee": active_user.pk}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.ERROR, "Pick someone on staff.")],
        )
        notice_case.refresh_from_db()
        assert notice_case.assignee is None

    def test_closes_a_case_with_nothing_to_decide(self, staff_client):
        case = ModerationCase.objects.create(external_email="ola@example.com")

        response = staff_client.post(_url("close", case))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", case),
            messages=[(messages.SUCCESS, "Case closed.")],
        )
        case.refresh_from_db()
        assert case.status == "closed"

    def test_will_not_close_over_an_undecided_notice(self, staff_client, notice_case):
        response = staff_client.post(_url("close", notice_case))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.ERROR, "Decide the case's reports before closing it.")],
        )
        notice_case.refresh_from_db()
        assert notice_case.status == "open"


class TestDecide:
    def test_removes_the_message_tells_the_reporter_and_explains_to_the_author(
        self,
        staff_client,
        staff_user,
        chat_case,
        settings,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        configure_parley(settings)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as worker:
            worker.post(f"{WORKER}/moderation", status=204)
            worker.post(f"{WORKER}/conversations", status=204)
            worker.post(f"{WORKER}/conversations/messages", status=204)
            with django_capture_on_commit_callbacks(execute=True):
                response = _decide(staff_client, chat_case)
            posts = _tokens(worker, "/conversations/messages")
            urls = [call.request.url for call in worker.calls]

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", chat_case),
            messages=[(messages.SUCCESS, "Decision recorded. The case is closed.")],
        )
        report = ParleyReport.objects.get()
        assert (report.status, report.decision, report.decision_text) == (
            "actioned",
            "content_removed",
            DECISION_TEXT,
        )
        assert sorted(mail.to[0] for mail in mailoutbox) == [
            "author@example.com",
            "reporter@example.com",
        ]
        assert all(f"[Z-{chat_case.pk}]" in mail.subject for mail in mailoutbox)
        chat_case.refresh_from_db()
        assert (chat_case.status, chat_case.decided_by) == ("closed", staff_user)
        assert [post["author"] for post in posts] == ["system", str(staff_user.pk)]
        assert f"{WORKER}/moderation" in urls

    def test_when_the_chat_does_not_answer_nothing_is_decided(
        self, staff_client, chat_case, settings, mailoutbox
    ):
        configure_parley(settings)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as worker:
            worker.post(f"{WORKER}/moderation", status=503)
            response = _decide(staff_client, chat_case)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", chat_case),
            messages=[
                (
                    messages.ERROR,
                    (
                        "The chat did not answer, so nothing was removed or"
                        " decided. Try again."
                    ),
                )
            ],
        )
        assert ParleyReport.objects.get().status == "open"
        assert mailoutbox == []

    def test_a_notice_sends_its_statement_to_the_account_named(
        self, staff_client, notice_case, mailoutbox, django_capture_on_commit_callbacks
    ):
        UserFactory(username="marek", email="marek@example.com")

        with django_capture_on_commit_callbacks(execute=True):
            response = _decide(
                staff_client,
                notice_case,
                decision="warning",
                ground="terms_4_1_6",
                affected_account="marek",
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[(messages.SUCCESS, "Decision recorded. The case is closed.")],
        )
        assert sorted(mail.to[0] for mail in mailoutbox) == [
            "marek@example.com",
            "ola@example.com",
        ]
        assert ContentNotice.objects.get().status == "actioned"

    def test_an_account_nobody_has_stops_the_decision(
        self, staff_client, notice_case, mailoutbox
    ):
        response = _decide(staff_client, notice_case, affected_account="nikt")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("case", notice_case),
            messages=[
                (
                    messages.ERROR,
                    "No single account matches. Give its username, slug or email.",
                )
            ],
        )
        assert ContentNotice.objects.get().status == "open"
        assert mailoutbox == []

    def test_a_verdict_that_does_not_hold_together_shows_the_form_again(
        self, staff_client, staff_user, notice_case
    ):
        response = _decide(staff_client, notice_case, ground="illegal_content")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user),
        )
        form = response.context_data["decision_form"]
        assert form.non_field_errors() == [
            (
                "This decision is incomplete: Name the provision of law the"
                " content breaks."
            )
        ]
        assert ContentNotice.objects.get().status == "open"

    def test_an_unknown_decision_shows_the_form_again(
        self, staff_client, staff_user, notice_case
    ):
        response = _decide(staff_client, notice_case, decision="ban_forever")

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(notice_case, staff_user),
        )
        assert list(response.context_data["decision_form"].errors) == ["decision"]
