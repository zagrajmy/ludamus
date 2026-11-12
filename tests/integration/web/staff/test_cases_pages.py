from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.pages import CONTENT_DIR
from ludamus.gates.web.django.staff.forms import GROUND_LABELS
from ludamus.inits.services import Services
from ludamus.links.db.django.models import StaffCase, StaffCaseDecision, StaffCaseEmail
from ludamus.pacts.staff_cases import (
    InboundEmail,
    ModerationAction,
    ModerationGround,
    StaffCaseDetailDTO,
    StaffCaseDTO,
    StaffCaseKind,
    StaffCaseListItemDTO,
    StaffCaseStatus,
    StaffEmailDirection,
    StaffInboxDTO,
    StaffMemberDTO,
)
from ludamus.pacts.staff_cases import StaffCaseEmailDTO as EmailDTO
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response, assert_response_404

CASES = reverse("web:staff:cases")
FAQ = (CONTENT_DIR / "moderation-faq.md").read_text(encoding="utf-8")


def _case(*, subject="Pytanie o moderację"):
    receipt = Services().staff_cases.receive_email(
        InboundEmail(
            message_id=f"<{subject}@mail.example>",
            from_address="ola@example.com",
            from_name="Ola W.",
            subject=subject,
            body="Dzień dobry.",
            attachments=[],
        )
    )
    return StaffCase.objects.get(pk=receipt.case_id)


def _tabs(*, active="open", open_=0, waiting=0, closed=0):
    return [
        {
            "key": "open",
            "icon": "inbox",
            "label": "Open",
            "count": open_,
            "active": active == "open",
        },
        {
            "key": "waiting",
            "icon": "clock",
            "label": "Waiting",
            "count": waiting,
            "active": active == "waiting",
        },
        {
            "key": "closed",
            "icon": "check-circle",
            "label": "Closed",
            "count": closed,
            "active": active == "closed",
        },
    ]


def _counts(*, open_=0, waiting=0, closed=0):
    return {
        StaffCaseStatus.OPEN: open_,
        StaffCaseStatus.WAITING: waiting,
        StaffCaseStatus.CLOSED: closed,
    }


def _item(case):
    return StaffCaseListItemDTO(
        pk=case.pk,
        kind=StaffCaseKind(case.kind),
        status=StaffCaseStatus(case.status),
        title=case.title,
        child_safety=case.child_safety,
        assignee_name="",
        created_at=case.created_at,
    )


class TestStaffOnly:
    @pytest.mark.parametrize(
        "name", ("web:staff:case", "web:staff:reply", "web:staff:decide")
    )
    def test_someone_not_on_staff_gets_a_404_and_changes_nothing(
        self, authenticated_client, name
    ):
        case = _case()

        response = (
            authenticated_client.get
            if name == "web:staff:case"
            else authenticated_client.post
        )(
            reverse(name, kwargs={"pk": case.pk}),
            {"body": "Hej", "send": "email", "action": "hide", "ground": "illegal"},
        )

        assert_response_404(response)
        assert StaffCaseEmail.objects.count() == 1
        assert not StaffCaseDecision.objects.exists()

    def test_the_inbox_is_a_404_signed_out_and_off_staff(
        self, client, authenticated_client
    ):
        assert_response_404(client.get(CASES))
        assert_response_404(authenticated_client.get(CASES))

    def test_an_unknown_case_is_a_404(self, staff_client):
        assert_response_404(
            staff_client.get(reverse("web:staff:case", kwargs={"pk": 404}))
        )


class TestInboxPage:
    def test_staff_see_open_cases_and_the_count_of_each_state(self, staff_client):
        case = _case()

        response = staff_client.get(CASES)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data={
                "inbox": StaffInboxDTO(
                    status=StaffCaseStatus.OPEN,
                    cases=[_item(case)],
                    counts=_counts(open_=1),
                ),
                "tabs": _tabs(open_=1),
                "faq": FAQ,
                "detail": None,
            },
        )

    def test_an_unknown_state_shows_the_open_cases(self, staff_client):
        response = staff_client.get(CASES, {"status": "lost"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data={
                "inbox": StaffInboxDTO(
                    status=StaffCaseStatus.OPEN, cases=[], counts=_counts()
                ),
                "tabs": _tabs(),
                "faq": FAQ,
                "detail": None,
            },
        )


def _case_page(
    case,
    *,
    staff_user,
    action=ModerationAction.HIDE,
    ground=ModerationGround.UNLAWFUL_OR_INDECENT,
):
    return {
        "inbox": StaffInboxDTO(
            status=StaffCaseStatus.OPEN, cases=[_item(case)], counts=_counts(open_=1)
        ),
        "tabs": _tabs(open_=1),
        "faq": FAQ,
        "detail": StaffCaseDetailDTO(
            case=StaffCaseDTO(
                pk=case.pk,
                kind=StaffCaseKind.EMAIL,
                status=StaffCaseStatus.OPEN,
                title="Pytanie o moderację",
                child_safety=False,
                assignee_id=None,
                conversation_id=case.conversation_id,
                external_email="ola@example.com",
                external_name="Ola W.",
                report_id=None,
                notice_id=None,
                decision=None,
                created_at=case.created_at,
            ),
            content=None,
            emails=[
                EmailDTO(
                    direction=StaffEmailDirection.IN,
                    address="ola@example.com",
                    name="Ola W.",
                    subject="Pytanie o moderację",
                    body="Dzień dobry.",
                    attachments=[],
                    sent_by_name="",
                    created_at=StaffCaseEmail.objects.get().created_at,
                )
            ],
            staff=[StaffMemberDTO(pk=staff_user.pk, name=staff_user.get_full_name())],
            may_decide=True,
        ),
        "reply_form": ANY,
        "assign_form": ANY,
        "decision_form": ANY,
        "statement": {"action": action, "ground": GROUND_LABELS[ground]},
    }


class TestCasePage:
    def test_shows_the_case_its_mail_and_who_can_take_it(
        self, staff_client, staff_user
    ):
        case = _case()

        response = staff_client.get(reverse("web:staff:case", kwargs={"pk": case.pk}))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(case, staff_user=staff_user),
        )

    def test_previews_the_statement_for_the_action_picked(
        self, staff_client, staff_user
    ):
        case = _case()

        response = staff_client.get(
            reverse("web:staff:case", kwargs={"pk": case.pk}),
            {"action": "remove", "ground": "illegal"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(
                case,
                staff_user=staff_user,
                action=ModerationAction.REMOVE,
                ground=ModerationGround.ILLEGAL,
            ),
        )


class TestReply:
    def test_by_email_goes_from_staff_with_the_case_number(
        self, staff_client, staff_user, mailoutbox, django_capture_on_commit_callbacks
    ):
        case = _case()
        url = reverse("web:staff:reply", kwargs={"pk": case.pk})

        with django_capture_on_commit_callbacks(execute=True):
            response = staff_client.post(url, {"body": "Dziękujemy.", "send": "email"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[(messages.SUCCESS, "Reply sent.")],
        )
        (mail,) = mailoutbox
        assert (mail.to, mail.from_email, mail.subject, mail.body) == (
            ["ola@example.com"],
            "Zagrajmy <staff@zagrajmy.net>",
            f"[Z-{case.pk}] Pytanie o moderację",
            "Dziękujemy.",
        )
        sent = StaffCaseEmail.objects.get(direction="out")
        assert mail.extra_headers["Message-ID"] == (
            f"<case-{sent.message_id}@zagrajmy.net>"
        )
        assert sent.sent_by == staff_user
        assert StaffCase.objects.get().status == "waiting"

    def test_a_note_stays_inside(
        self, staff_client, mailoutbox, django_capture_on_commit_callbacks
    ):
        case = _case()

        with django_capture_on_commit_callbacks(execute=True):
            response = staff_client.post(
                reverse("web:staff:reply", kwargs={"pk": case.pk}),
                {"body": "Sprawdzam", "send": "note"},
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[(messages.SUCCESS, "Note added to the thread.")],
        )
        assert mailoutbox == []
        assert StaffCaseEmail.objects.count() == 1

    def test_an_empty_reply_shows_the_form_again(self, staff_client, staff_user):
        case = _case()

        response = staff_client.post(
            reverse("web:staff:reply", kwargs={"pk": case.pk}),
            {"body": "", "send": "email"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(case, staff_user=staff_user),
        )
        form = response.context_data["reply_form"]
        assert form.errors == {"body": ["This field is required."]}


class TestAssign:
    def test_hands_the_case_to_someone_on_staff(self, staff_client):
        case = _case()
        other = UserFactory(is_staff=True)

        response = staff_client.post(
            reverse("web:staff:assign", kwargs={"pk": case.pk}), {"assignee": other.pk}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[(messages.SUCCESS, "Case assigned.")],
        )
        assert StaffCase.objects.get().assignee == other

    def test_refuses_someone_off_staff(self, staff_client, active_user):
        case = _case()

        response = staff_client.post(
            reverse("web:staff:assign", kwargs={"pk": case.pk}),
            {"assignee": active_user.pk},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[(messages.ERROR, "Pick someone on staff.")],
        )
        assert StaffCase.objects.get().assignee is None


class TestDecide:
    def test_records_the_decision_and_closes_the_case(self, staff_client, staff_user):
        case = _case()

        response = staff_client.post(
            reverse("web:staff:decide", kwargs={"pk": case.pk}),
            {"action": "hide", "ground": "terms_4_1_7"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[(messages.SUCCESS, "Decision recorded. The case is closed.")],
        )
        decision = StaffCaseDecision.objects.get()
        assert (decision.action, decision.ground, decision.decided_by) == (
            "hide",
            "terms_4_1_7",
            staff_user,
        )
        assert (StaffCase.objects.get().status, StaffCase.objects.get().decision) == (
            "closed",
            decision,
        )

    def test_whoever_decided_cannot_decide_the_appeal(self, staff_client):
        case = _case()
        url = reverse("web:staff:decide", kwargs={"pk": case.pk})
        staff_client.post(url, {"action": "hide", "ground": "terms_4_1_7"})

        response = staff_client.post(url, {"action": "none", "ground": "terms_4_1_7"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:staff:case", kwargs={"pk": case.pk}),
            messages=[
                (messages.SUCCESS, "Decision recorded. The case is closed."),
                (
                    messages.ERROR,
                    "You made the decision under appeal. Someone else decides it.",
                ),
            ],
        )
        assert StaffCaseDecision.objects.count() == 1

    def test_an_unknown_action_shows_the_form_again(self, staff_client, staff_user):
        case = _case()

        response = staff_client.post(
            reverse("web:staff:decide", kwargs={"pk": case.pk}),
            {"action": "ban_forever", "ground": "terms_4_1_7"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="staff/cases.html",
            context_data=_case_page(case, staff_user=staff_user),
        )
        assert list(response.context_data["decision_form"].errors) == ["action"]
        assert not StaffCaseDecision.objects.exists()
