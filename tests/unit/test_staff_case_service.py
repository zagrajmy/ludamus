"""StaffCaseService against an in-memory world.

What could go wrong, and so what the tests below check:
- someone not on staff reads or changes a case;
- a child-safety case sinks below newer ones, or a case is named by the wrong kind;
- a case's thread keeps someone no longer on staff, misses someone new, is
  opened twice, or every inbox visit resends every thread's members;
- a redelivered email files twice or posts twice into the thread;
- an email naming a case lands in a new one, one naming no case that exists
  is dropped, or a reply to a waiting or closed case leaves it there;
- a note reaches the outside, or a reply by email goes nowhere, to the wrong
  person, or without the case number in its subject;
- a case is handed to someone not on staff, or closed with reports undecided;
- deciding in the inbox does less than the admin: the chat message stays,
  reporters are not told, the author gets no statement; or it acts on a
  verdict that does not hold together, or decides after the chat failed.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from ludamus.mills.parley_conversations import visible_conversations
from ludamus.mills.staff_cases import (
    StaffCaseService,
    reply_subject,
    subject_reference,
    verdict_of,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    InvalidVerdictError,
    ModerationDecision,
    ModerationDecisionsDTO,
    ModerationGround,
    ModerationStatus,
    ModerationVerdict,
    NoticeCategory,
)
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyMemberState,
    ParleyModerationResult,
)
from ludamus.pacts.staff_cases import (
    CASE_TITLE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseChatReportDTO,
    CaseDTO,
    CaseEmailDirection,
    CaseKind,
    CaseNoticeDTO,
    CaseRowDTO,
    CaseStatus,
    InboundEmail,
    StaffCaseError,
    StaffDecision,
    StaffEmailOutcome,
    StaffMemberDTO,
    StaffThreadEvent,
)
from ludamus.specs.staff_cases import STAFF_CASE_RETENTION
from tests.unit.factories import FakeTransaction

PIOTR, RADEK, OUTSIDER, AUTHOR = 1, 2, 3, 4
T0 = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
OPEN, ACTIONED = ModerationStatus.OPEN, ModerationStatus.ACTIONED


def _notice(pk=7, *, category=NoticeCategory.HARASSMENT, status=OPEN):
    return CaseNoticeDTO(
        pk=pk,
        url="https://zagrajmy.net/e/abc",
        category=category,
        explanation="Obraźliwy opis",
        reporter_name="Ola W.",
        status=status,
    )


def _report(pk=8, *, minor=False, status=OPEN):
    return CaseChatReportDTO(
        pk=pk,
        room_id="conversation:5",
        reason="Prosi o telefon",
        reporter_name="Ola W.",
        author_name="Marek K.",
        author_age_band=None,
        author_joined_at=None,
        body="daj mi swój telefon",
        written_at=None,
        status=status,
        involves_minor=minor,
    )


class World:
    def __init__(self) -> None:
        self.staff = {PIOTR: "Piotr", RADEK: "Radek"}
        self.cases: dict[int, CaseDTO] = {}
        self.threads: dict[int, set[int]] = {}
        self.emails: list[dict] = []
        self.accounts = {"marek": AUTHOR}
        self.clock = T0

    def add_case(self, *, notices=(), reports=(), reply_to="ola@example.com"):
        self.clock += timedelta(minutes=1)
        pk = 1000 + len(self.cases)
        self.cases[pk] = CaseDTO(
            pk=pk,
            status=CaseStatus.OPEN,
            title="",
            assignee_id=None,
            decided_by_name="",
            thread_id=None,
            reply_to=reply_to,
            reply_name="Ola W.",
            opened_by_email=False,
            notices=list(notices),
            chat_reports=list(reports),
            verdict=None,
            created_at=self.clock,
        )
        return pk

    def _update(self, case_id, **changes):
        self.cases[case_id] = self.cases[case_id].model_copy(update=changes)

    def read_staff(self, user_id):
        name = self.staff.get(user_id)
        return None if name is None else StaffMemberDTO(pk=user_id, name=name)

    def list_staff(self):
        return [StaffMemberDTO(pk=pk, name=name) for pk, name in self.staff.items()]

    def open_for_email(self, data):
        pk = self.add_case(reply_to=data["external_email"])
        self._update(pk, title=data["title"], opened_by_email=True)
        return pk

    def open_thread(self, case_id):
        thread_id = 100 + len(self.threads)
        self.threads[thread_id] = set()
        self._update(case_id, thread_id=thread_id)
        return thread_id

    def set_thread_members(self, *, user_ids, thread_ids):
        changed = []
        for thread_id in self.threads if thread_ids is None else thread_ids:
            if self.threads[thread_id] != set(user_ids):
                self.threads[thread_id] = set(user_ids)
                changed.append(thread_id)
        return changed

    def read(self, case_id):
        if case_id not in self.cases:
            raise NotFoundError
        return self.cases[case_id]

    def list_cases(self, status):
        return [
            CaseRowDTO(
                pk=case.pk,
                status=case.status,
                title=case.title,
                assignee_name="",
                created_at=case.created_at,
                has_notices=bool(case.notices),
                has_chat_reports=bool(case.chat_reports),
                opened_by_email=case.opened_by_email,
                notice_categories=[notice.category for notice in case.notices],
                involves_minor=any(r.involves_minor for r in case.chat_reports),
            )
            for case in self.cases.values()
            if case.status == status
        ]

    def count_by_status(self):
        return {
            status: sum(case.status == status for case in self.cases.values())
            for status in CaseStatus
        }

    def set_status(self, *, case_id, status):
        self._update(case_id, status=status)

    def set_assignee(self, *, case_id, assignee_id):
        self._update(case_id, assignee_id=assignee_id)

    def set_decided_by(self, *, case_id, user_id):
        self._update(case_id, decided_by_name=self.staff[user_id])

    def email_seen(self, message_id):
        return next(
            (e["case_id"] for e in self.emails if e["message_id"] == message_id), None
        )

    def add_email(self, data):
        self.emails.append(data)

    @staticmethod
    def list_emails(_case_id):
        return []

    def find_account(self, identifier):
        return self.accounts.get(identifier)


class Outside:
    """The chat, the mailer, the member list outbox and #1759's decisions."""

    def __init__(self, *, removes=True) -> None:
        self.posts = []
        self.replies = []
        self.synced = []
        self.removed = []
        self.reports_decided = []
        self.notices_decided = []
        self.removes = removes

    def post(self, entry):
        self.posts.append(entry)

    def send_reply(self, **mail):
        self.replies.append(mail)

    @staticmethod
    def statement_text(statement):
        return f"{statement.decision}: {statement.ground}: {statement.facts}"

    def schedule(self, *, conversation_ids):
        self.synced.append(conversation_ids)

    @staticmethod
    def check(verdict):
        if verdict.status == ModerationStatus.ACTIONED and verdict.ground is None:
            msg = "An actioned report names its ground."
            raise InvalidVerdictError(msg)

    def decide_chat_reports(self, *, report_ids, verdict):
        self.reports_decided.append((report_ids, verdict))
        return ModerationDecisionsDTO(decided=len(report_ids), statements=[])

    def decide_notices(self, *, notice_ids, verdict, affected_user_id):
        self.notices_decided.append((notice_ids, verdict, affected_user_id))
        return ModerationDecisionsDTO(decided=len(notice_ids), statements=[])

    def delete_reported(self, *, report_ids, now):
        self.removed.append((report_ids, now.tzinfo))
        deleted = len(report_ids) if self.removes else 0
        return ParleyModerationResult(deleted=deleted, failed=len(report_ids) - deleted)


@pytest.fixture(name="world")
def world_fixture():
    return World()


@pytest.fixture(name="out")
def out_fixture():
    return Outside()


@pytest.fixture(name="service")
def service_fixture(world, out):
    return _service(world, out)


def _service(world, out):
    return StaffCaseService(
        transaction=FakeTransaction(),
        repository=world,
        thread=out,
        mailer=out,
        memberships=out,
        decisions=out,
        chat=out,
    )


def _email(**overrides):
    return InboundEmail(
        **{
            "message_id": "<a@example.com>",
            "from_address": "ola@example.com",
            "from_name": "Ola W.",
            "subject": "Zgłoszenie",
            "body": "Proszę o pomoc.",
            "attachments": [],
            **overrides,
        }
    )


def _decision(**overrides):
    return StaffDecision(
        **{
            "decision": ModerationDecision.CONTENT_REMOVED,
            "ground": ModerationGround.TERMS_UNLAWFUL_CONTENT,
            "decision_text": "Prośba o telefon do dziecka.",
            **overrides,
        }
    )


class TestStaffOnly:
    @pytest.mark.parametrize(
        "call",
        (
            lambda s: s.inbox(actor_id=OUTSIDER, status=CaseStatus.OPEN),
            lambda s: s.read(actor_id=OUTSIDER, case_id=1000),
            lambda s: s.reply(
                actor_id=OUTSIDER, case_id=1000, body="x", by_email=False
            ),
            lambda s: s.assign(actor_id=OUTSIDER, case_id=1000, assignee_id=PIOTR),
            lambda s: s.close(actor_id=OUTSIDER, case_id=1000),
            lambda s: s.decide(actor_id=OUTSIDER, case_id=1000, decision=_decision()),
        ),
    )
    def test_someone_not_on_staff_finds_nothing(self, service, world, out, call):
        world.add_case(reports=[_report()])

        with pytest.raises(NotFoundError):
            call(service)

        assert (out.posts, out.reports_decided, world.threads) == ([], [], {})


class TestInbox:
    def test_lists_child_safety_first_then_newest_with_counts(self, service, world):
        plain = world.add_case(notices=[_notice()])
        grooming = world.add_case(
            notices=[_notice(category=NoticeCategory.CHILD_SAFETY)]
        )
        minor = world.add_case(reports=[_report(minor=True)])
        newest = world.add_case(reports=[_report()])

        inbox = service.inbox(actor_id=PIOTR, status=CaseStatus.OPEN)

        assert [case.pk for case in inbox.cases] == [minor, grooming, newest, plain]
        assert inbox.counts == {
            CaseStatus.OPEN: 4,
            CaseStatus.WAITING: 0,
            CaseStatus.CLOSED: 0,
        }

    def test_names_each_case_by_what_opened_it(self, service, world):
        world.add_case(notices=[_notice()], reports=[_report()])
        world.add_case(reports=[_report()])
        service.receive_email(_email())
        world.add_case(reply_to="")

        inbox = service.inbox(actor_id=PIOTR, status=CaseStatus.OPEN)

        assert sorted(case.kind for case in inbox.cases) == sorted(
            [CaseKind.NOTICE, CaseKind.CHAT_REPORT, CaseKind.EMAIL, CaseKind.STATEMENT]
        )

    def test_brings_every_thread_in_step_with_staff_once(self, service, world, out):
        service.receive_email(_email())
        world.staff[5] = "Nowa"
        del world.staff[RADEK]

        service.inbox(actor_id=PIOTR, status=CaseStatus.OPEN)
        service.inbox(actor_id=PIOTR, status=CaseStatus.OPEN)

        assert world.threads == {100: {PIOTR, 5}}
        assert out.synced[-2:] == [[100], []]


class TestRead:
    def test_opens_the_thread_once_with_staff_and_says_what_the_case_is(
        self, service, world, out
    ):
        case_id = world.add_case(reports=[_report(minor=True)])

        first = service.read(actor_id=RADEK, case_id=case_id)
        again = service.read(actor_id=PIOTR, case_id=case_id)

        assert (first.case.thread_id, again.case.thread_id) == (100, 100)
        assert world.threads == {100: {PIOTR, RADEK}}
        assert [(p.event, p.retain_for, p.details["kind"]) for p in out.posts] == [
            (StaffThreadEvent.CASE_OPENED, STAFF_CASE_RETENTION, CaseKind.CHAT_REPORT)
        ]
        assert (first.kind, first.child_safety, first.decidable) == (
            CaseKind.CHAT_REPORT,
            True,
            True,
        )
        assert [member.name for member in first.staff] == ["Piotr", "Radek"]

    def test_a_decided_case_has_nothing_to_decide(self, service, world):
        case_id = world.add_case(notices=[_notice(status=ACTIONED)])

        assert service.read(actor_id=PIOTR, case_id=case_id).decidable is False


class TestInboundEmail:
    def test_without_a_case_number_opens_one_for_the_sender(self, service, world, out):
        receipt = service.receive_email(_email(subject="  Naruszenie   w opisie "))

        case = world.cases[receipt.case_id]
        assert receipt.outcome == StaffEmailOutcome.OPENED
        assert (case.title, case.reply_to, case.thread_id) == (
            "Naruszenie w opisie",
            "ola@example.com",
            100,
        )
        assert [post.event for post in out.posts] == [
            StaffThreadEvent.CASE_OPENED,
            StaffThreadEvent.EMAIL_IN,
        ]

    def test_naming_a_case_reopens_it(self, service, world, out):
        case_id = world.add_case(reports=[_report(status=ACTIONED)])
        world.set_status(case_id=case_id, status=CaseStatus.CLOSED)

        receipt = service.receive_email(
            _email(subject=f"Re: Fwd: [z-{case_id}] wynik", attachments=["a.png"])
        )

        assert (receipt.outcome, receipt.case_id) == (
            StaffEmailOutcome.ATTACHED,
            case_id,
        )
        assert world.cases[case_id].status == CaseStatus.OPEN
        assert out.posts[-1].details["attachments"] == "1"

    def test_naming_no_case_there_is_opens_one(self, service, world):
        receipt = service.receive_email(_email(subject="[Z-999] stara sprawa"))

        assert receipt.outcome == StaffEmailOutcome.OPENED
        assert len(world.cases) == 1

    def test_delivered_twice_files_once_and_posts_once(self, service, world, out):
        first = service.receive_email(_email())

        again = service.receive_email(_email())

        assert (again.outcome, again.case_id) == (
            StaffEmailOutcome.DUPLICATE,
            first.case_id,
        )
        assert (len(world.emails), len(out.posts)) == (1, 2)

    def test_posts_under_a_nonce_its_message_id_decides(self, service, out):
        service.receive_email(_email(message_id="<x@y>"))
        service.receive_email(_email(message_id="<z@y>"))

        nonces = [p.nonce for p in out.posts if p.event == StaffThreadEvent.EMAIL_IN]
        assert len(set(nonces)) == len(nonces) == len(["<x@y>", "<z@y>"])
        assert all(nonce.startswith("email-") for nonce in nonces)

    def test_a_long_subject_and_body_are_clipped(self, service, world, out):
        case_id = service.receive_email(
            _email(subject="a" * 500, body="b" * 10_000)
        ).case_id

        title = world.cases[case_id].title
        assert (len(title), title[-1]) == (CASE_TITLE_MAX_LENGTH, "…")
        assert len(out.posts[-1].body) == STAFF_THREAD_POST_MAX_LENGTH


class TestReply:
    @pytest.fixture(name="case_id")
    def case_id_fixture(self, service):
        return service.receive_email(_email(subject="Pytanie")).case_id

    def test_by_email_goes_to_the_sender_with_the_case_number(
        self, service, world, out, case_id
    ):
        service.reply(
            actor_id=PIOTR, case_id=case_id, body=" Dziękujemy. ", by_email=True
        )

        assert out.replies == [
            {
                "to": "ola@example.com",
                "subject": f"[Z-{case_id}] Pytanie",
                "body": "Dziękujemy.",
                "nonce": world.emails[-1]["message_id"],
            }
        ]
        assert (world.emails[-1]["direction"], world.emails[-1]["sent_by_id"]) == (
            CaseEmailDirection.OUT,
            PIOTR,
        )
        assert world.cases[case_id].status == CaseStatus.WAITING
        assert (out.posts[-1].event, out.posts[-1].author_name) == (
            StaffThreadEvent.EMAIL_OUT,
            "Piotr",
        )

    def test_a_note_stays_in_the_thread(self, service, world, out, case_id):
        service.reply(actor_id=RADEK, case_id=case_id, body="Sprawdzam", by_email=False)

        assert (out.replies, len(world.emails)) == ([], 1)
        assert (out.posts[-1].event, out.posts[-1].author_id) == (
            StaffThreadEvent.NOTE,
            RADEK,
        )

    @pytest.mark.parametrize("body", ("   ", "x" * (STAFF_REPLY_MAX_LENGTH + 1)))
    def test_refuses_an_empty_or_overlong_reply(self, service, out, case_id, body):
        with pytest.raises(StaffCaseError, match="invalid_body"):
            service.reply(actor_id=PIOTR, case_id=case_id, body=body, by_email=True)

        assert out.replies == []

    def test_by_email_with_nobody_to_answer_is_refused(self, service, world, out):
        case_id = world.add_case(reply_to="")

        with pytest.raises(StaffCaseError, match="no_recipient"):
            service.reply(actor_id=PIOTR, case_id=case_id, body="Hej", by_email=True)

        assert out.replies == []


class TestAssignAndClose:
    def test_hands_a_case_to_staff_and_back_to_nobody(self, service, world):
        case_id = world.add_case()

        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=RADEK)
        assigned = world.cases[case_id].assignee_id
        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=None)

        assert (assigned, world.cases[case_id].assignee_id) == (RADEK, None)

    def test_refuses_someone_not_on_staff(self, service, world):
        case_id = world.add_case()

        with pytest.raises(StaffCaseError, match="invalid_assignee"):
            service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=OUTSIDER)

        assert world.cases[case_id].assignee_id is None

    def test_closes_a_case_with_nothing_to_decide(self, service, world):
        case_id = world.add_case(notices=[_notice(status=ACTIONED)])

        service.close(actor_id=PIOTR, case_id=case_id)

        assert world.cases[case_id].status == CaseStatus.CLOSED

    def test_will_not_close_over_an_open_report(self, service, world):
        case_id = world.add_case(reports=[_report()])

        with pytest.raises(StaffCaseError, match="undecided"):
            service.close(actor_id=PIOTR, case_id=case_id)

        assert world.cases[case_id].status == CaseStatus.OPEN


class TestDecide:
    def test_removing_chat_content_deletes_it_then_decides_its_reports(
        self, service, world, out
    ):
        case_id = world.add_case(reports=[_report(8), _report(9, status=ACTIONED)])

        service.decide(actor_id=RADEK, case_id=case_id, decision=_decision())

        assert out.removed == [([8], UTC)]
        ((report_ids, verdict),) = out.reports_decided
        assert (report_ids, verdict.status, verdict.ground) == (
            [8],
            ACTIONED,
            ModerationGround.TERMS_UNLAWFUL_CONTENT,
        )
        case = world.cases[case_id]
        assert (case.status, case.decided_by_name) == (CaseStatus.CLOSED, "Radek")
        assert (out.posts[-1].event, out.posts[-1].details["status"]) == (
            StaffThreadEvent.DECISION,
            ACTIONED,
        )

    def test_when_the_chat_does_not_answer_nothing_is_decided(self, world):
        out = Outside(removes=False)
        case_id = world.add_case(reports=[_report()])

        with pytest.raises(StaffCaseError, match="chat_unavailable"):
            _service(world, out).decide(
                actor_id=PIOTR, case_id=case_id, decision=_decision()
            )

        assert (out.reports_decided, world.cases[case_id].status) == (
            [],
            CaseStatus.OPEN,
        )

    def test_a_warning_leaves_the_message_and_still_decides(self, service, world, out):
        case_id = world.add_case(reports=[_report()])

        service.decide(
            actor_id=PIOTR,
            case_id=case_id,
            decision=_decision(decision=ModerationDecision.WARNING),
        )

        assert out.removed == []
        assert out.reports_decided[0][1].decision == ModerationDecision.WARNING

    def test_a_notice_names_the_account_its_statement_goes_to(
        self, service, world, out
    ):
        case_id = world.add_case(notices=[_notice()])

        service.decide(
            actor_id=PIOTR,
            case_id=case_id,
            decision=_decision(
                decision=ModerationDecision.ACCOUNT_SUSPENDED,
                suspended_until=date(2026, 12, 1),
                affected_account=" marek ",
            ),
        )

        ((notice_ids, verdict, affected),) = out.notices_decided
        assert (notice_ids, verdict.suspended_until, affected) == (
            [7],
            date(2026, 12, 1),
            AUTHOR,
        )

    @pytest.mark.parametrize(
        ("account", "code"), (("nikt", "unknown_account"), ("marek", "no_notice"))
    )
    def test_an_account_that_cannot_be_named_stops_the_decision(
        self, service, world, out, account, code
    ):
        records = {"notices": [_notice()]} if code == "unknown_account" else {}
        case_id = world.add_case(reports=[_report()], **records)

        with pytest.raises(StaffCaseError, match=code):
            service.decide(
                actor_id=PIOTR,
                case_id=case_id,
                decision=_decision(affected_account=account),
            )

        assert (out.removed, out.reports_decided, out.notices_decided) == ([], [], [])

    def test_with_everything_decided_there_is_nothing_to_decide(self, service, world):
        case_id = world.add_case(reports=[_report(status=ACTIONED)])

        with pytest.raises(StaffCaseError, match="nothing_to_decide"):
            service.decide(actor_id=PIOTR, case_id=case_id, decision=_decision())

    def test_a_verdict_that_does_not_hold_together_acts_on_nothing(
        self, service, world, out
    ):
        case_id = world.add_case(reports=[_report()])

        with pytest.raises(InvalidVerdictError):
            service.decide(
                actor_id=PIOTR, case_id=case_id, decision=_decision(ground=None)
            )

        assert (out.removed, out.reports_decided) == ([], [])


class TestVerdictAndPreview:
    def test_no_action_rejects_the_reports_whatever_ground_was_left(self):
        verdict = verdict_of(_decision(decision=ModerationDecision.NO_ACTION))

        assert verdict == ModerationVerdict(
            status=ModerationStatus.REJECTED,
            decision=ModerationDecision.NO_ACTION,
            ground=None,
            decision_text="Prośba o telefon do dziecka.",
        )

    def test_previews_the_statement_the_author_would_get(self, service):
        assert service.preview(_decision()) == (
            "content_removed: terms_4_1_7: Prośba o telefon do dziecka."
        )

    def test_no_action_has_no_statement(self, service):
        assert not service.preview(_decision(decision=ModerationDecision.NO_ACTION))


class TestSubjects:
    @pytest.mark.parametrize(
        ("subject", "number"),
        (
            ("[Z-1234] Ukryliśmy", 1234),
            ("Re: Fwd: [z-7] wynik", 7),
            ("Z-12 bez nawiasów", None),
            ("", None),
        ),
    )
    def test_finds_the_case_number_in_brackets(self, subject, number):
        assert subject_reference(subject) == number

    def test_a_reply_without_a_title_still_names_the_case(self, world):
        case_id = world.add_case()

        assert reply_subject(world.cases[case_id]) == f"[Z-{case_id}] (bez tematu)"


def test_a_case_thread_stays_listed_without_direct_messages():
    thread = ParleyConversationDTO(
        id="conversation:9",
        kind=ParleyConversationKind.STAFF,
        title="Z-1",
        name="Z-1",
        state=ParleyMemberState.ACTIVE,
        can_write=True,
        is_admin=False,
        members=[],
    )

    assert visible_conversations([thread], direct=False) == [thread]
