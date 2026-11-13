"""StaffCaseService against an in-memory world.

What could go wrong, and so what the tests below check:
- someone not on staff reads or changes a case;
- the inbox asks for child safety by the wrong categories, or the wrong page;
- a case's thread is opened twice, misses someone on staff, or keeps someone
  no longer on staff;
- a redelivered email files twice or posts twice into the thread;
- an email naming a case lands in a new one, one naming no case that exists
  is dropped, or a reply to a waiting or closed case leaves it there;
- a reply goes nowhere, to a stranger who named the case, or without the
  case number in its subject, or with a subject too long to file;
- a case is handed to someone not on staff, or closed with reports undecided;
- deciding in the inbox does less than the admin: the chat message stays,
  reporters are not told, the author gets no statement; or it acts on a
  verdict that does not hold together, or decides after the chat failed to
  remove even one message; two staff deciding at once both post a decision;
- a case's mail outlives its three years.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from ludamus.mills.parley_conversations import visible_conversations
from ludamus.mills.staff_cases import (
    CaseMailRetentionService,
    StaffCaseService,
    reply_target,
    subject_reference,
    verdict_of,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.moderation import (
    CaseStatus,
    InvalidVerdictError,
    ModerationDecision,
    ModerationDecisionsDTO,
    ModerationGround,
    ModerationStatus,
    ModerationVerdict,
)
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyMemberState,
    ParleyModerationResult,
)
from ludamus.pacts.staff_cases import (
    CASE_EMAIL_LINE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    CaseChatReportDTO,
    CaseDTO,
    CaseEmailDirection,
    CaseKind,
    CaseNoticeDTO,
    CaseOpenedPost,
    CasePersonDTO,
    DecisionPost,
    EmailInPost,
    EmailOutPost,
    InboundEmail,
    InboxCaseDTO,
    StaffCaseError,
    StaffCaseErrorCode,
    StaffDecision,
    StaffEmailOutcome,
    StaffMemberDTO,
)
from ludamus.specs.moderation import URGENT_NOTICE_CATEGORIES
from tests.unit.factories import FakeTransaction

PIOTR, RADEK, OUTSIDER, AUTHOR = 1, 2, 3, 4
T0 = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
OPEN, ACTIONED = ModerationStatus.OPEN, ModerationStatus.ACTIONED
STAFF = {PIOTR: StaffMemberDTO(pk=PIOTR, name="Piotr")}
OLA = CasePersonDTO(address="ola@example.com", name="Ola W.")


def _notice(pk=7, *, status=OPEN):
    return CaseNoticeDTO(
        pk=pk,
        url="https://zagrajmy.net/e/abc",
        category="harassment",
        explanation="Obraźliwy opis",
        reporter_name="Ola W.",
        status=status,
    )


def _report(pk=8, *, status=OPEN):
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
    )


class World:
    def __init__(self) -> None:
        self.staff = {PIOTR: "Piotr", RADEK: "Radek"}
        self.cases: dict[int, CaseDTO] = {}
        self.threads: dict[int, set[int]] = {}
        self.emails: list[dict] = []
        self.accounts = {"marek": AUTHOR}
        self.asked: list[tuple] = []
        self.now = T0

    def add_case(self, *, notices=(), reports=(), people=(OLA,)):
        pk = 1000 + len(self.cases)
        self.cases[pk] = CaseDTO(
            pk=pk,
            kind=CaseKind.CHAT_REPORT,
            status=CaseStatus.OPEN,
            title="",
            child_safety=False,
            assignee_name="",
            created_at=T0 + timedelta(minutes=pk),
            assignee_id=None,
            decided_by_name="",
            thread_id=None,
            people=list(people),
            senders=[],
            notices=list(notices),
            chat_reports=list(reports),
            verdict=None,
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
        pk = self.add_case(
            people=[
                CasePersonDTO(
                    address=data["external_email"], name=data["external_name"]
                )
            ]
        )
        self._update(pk, title=data["title"], kind=CaseKind.EMAIL)
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

    def read(self, case_id, *, urgent):
        assert urgent == URGENT_NOTICE_CATEGORIES
        if case_id not in self.cases:
            raise NotFoundError
        return self.cases[case_id]

    def list_cases(self, status, *, urgent, limit, offset):
        self.asked.append((status, urgent, limit, offset))
        return [
            InboxCaseDTO(**case.model_dump(include=set(InboxCaseDTO.model_fields)))
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
        self.emails.append(data | {"created_at": self.now})
        if data["direction"] == CaseEmailDirection.IN:
            case = self.cases[data["case_id"]]
            sender = CasePersonDTO(address=data["address"], name=data["name"])
            self._update(case.pk, senders=[sender, *case.senders])

    def forget_emails_before(self, cutoff):
        kept = [email for email in self.emails if email["created_at"] >= cutoff]
        forgotten, self.emails = len(self.emails) - len(kept), kept
        return forgotten

    @staticmethod
    def list_emails(_case_id):
        return []

    def find_account(self, identifier):
        return self.accounts.get(identifier)


class Outside:
    """The chat, the mailer, the member list outbox and the decisions."""

    def __init__(self, *, fails=0) -> None:
        self.posts = []
        self.replies = []
        self.synced = []
        self.removed = []
        self.reports_decided = []
        self.notices_decided = []
        self.fails = fails

    def post(self, entry):
        self.posts.append(entry)

    def send_reply(self, **mail):
        self.replies.append(mail)

    @staticmethod
    def verdict_text(verdict):
        return f"{verdict.status}: {verdict.decision_text}"

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
        failed = min(self.fails, len(report_ids))
        return ParleyModerationResult(deleted=len(report_ids) - failed, failed=failed)


class DecidedMeanwhile(Outside):
    """Another request decided every record between reading and deciding."""

    def decide_chat_reports(self, **asked):
        super().decide_chat_reports(**asked)
        return ModerationDecisionsDTO(decided=0, statements=[])

    def decide_notices(self, **asked):
        super().decide_notices(**asked)
        return ModerationDecisionsDTO(decided=0, statements=[])


@pytest.fixture(name="world")
def world_fixture():
    return World()


@pytest.fixture(name="out")
def out_fixture():
    return Outside()


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


@pytest.fixture(name="service")
def service_fixture(world, out):
    return _service(world, out)


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


def _messages(out):
    return [entry.message for entry in out.posts]


class TestStaffOnly:
    @pytest.mark.parametrize(
        "call",
        (
            lambda s: s.staff(actor_id=OUTSIDER),
            lambda s: s.counts(actor_id=OUTSIDER),
            lambda s: s.cases(
                actor_id=OUTSIDER, status=CaseStatus.OPEN, limit=10, offset=0
            ),
            lambda s: s.read(actor_id=OUTSIDER, case_id=1000),
            lambda s: s.reply(actor_id=OUTSIDER, case_id=1000, body="x"),
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
    def test_lists_a_page_of_one_state_asking_for_child_safety(self, service, world):
        case_id = world.add_case()

        cases = service.cases(
            actor_id=PIOTR, status=CaseStatus.OPEN, limit=20, offset=40
        )

        assert [case.pk for case in cases] == [case_id]
        assert world.asked == [(CaseStatus.OPEN, URGENT_NOTICE_CATEGORIES, 20, 40)]

    def test_counts_each_state_and_names_the_staff(self, service, world):
        world.add_case()

        assert service.counts(actor_id=RADEK) == {
            CaseStatus.OPEN: 1,
            CaseStatus.WAITING: 0,
            CaseStatus.CLOSED: 0,
        }
        assert [member.name for member in service.staff(actor_id=RADEK)] == [
            "Piotr",
            "Radek",
        ]

    def test_brings_every_thread_in_step_with_staff_once(self, service, world, out):
        service.receive_email(_email())
        world.staff[5] = "Nowa"
        del world.staff[RADEK]

        service.sync_threads()
        service.sync_threads()

        assert world.threads == {100: {PIOTR, 5}}
        assert out.synced[-2:] == [[100], []]


class TestRead:
    def test_opens_the_thread_once_with_staff_and_says_what_the_case_is(
        self, service, world, out
    ):
        case_id = world.add_case(reports=[_report()])

        first = service.read(actor_id=RADEK, case_id=case_id)
        again = service.read(actor_id=PIOTR, case_id=case_id)

        assert (first.case.thread_id, again.case.thread_id) == (100, 100)
        assert world.threads == {100: {PIOTR, RADEK}}
        assert _messages(out) == [CaseOpenedPost(kind=CaseKind.CHAT_REPORT, title="")]
        assert out.posts[0].reference == f"Z-{case_id}"
        assert (first.decidable, first.reply_to) == (True, OLA)

    def test_a_decided_case_has_nothing_to_decide(self, service, world):
        case_id = world.add_case(notices=[_notice(status=ACTIONED)])

        assert service.read(actor_id=PIOTR, case_id=case_id).decidable is False


class TestInboundEmail:
    def test_without_a_case_number_opens_one_for_the_sender(self, service, world, out):
        receipt = service.receive_email(_email(subject="Naruszenie w opisie"))

        case = world.cases[receipt.case_id]
        assert receipt.outcome == StaffEmailOutcome.OPENED
        assert (case.title, case.people, case.thread_id) == (
            "Naruszenie w opisie",
            [OLA],
            100,
        )
        assert _messages(out) == [
            CaseOpenedPost(kind=CaseKind.EMAIL, title="Naruszenie w opisie"),
            EmailInPost(sender="Ola W.", subject="Naruszenie w opisie"),
        ]

    def test_naming_a_case_reopens_it(self, service, world, out):
        case_id = world.add_case(reports=[_report(status=ACTIONED)])
        world.set_status(case_id=case_id, status=CaseStatus.CLOSED)

        receipt = service.receive_email(
            _email(
                subject=f"Re: Fwd: [z-{case_id}] wynik",
                from_name="",
                attachments=["a.png"],
            )
        )

        assert (receipt.outcome, receipt.case_id) == (
            StaffEmailOutcome.ATTACHED,
            case_id,
        )
        assert world.cases[case_id].status == CaseStatus.OPEN
        assert _messages(out)[-1] == EmailInPost(
            sender="ola@example.com", subject=f"Re: Fwd: [z-{case_id}] wynik"
        )

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

        nonces = [p.nonce for p in out.posts if p.message.event == "email_in"]
        assert len(set(nonces)) == len(nonces) == len(["<x@y>", "<z@y>"])
        assert all(nonce.startswith("email-") for nonce in nonces)

    def test_a_long_subject_is_clipped_to_the_title(self, service, world):
        case_id = service.receive_email(_email(subject="a" * 500)).case_id

        assert len(world.cases[case_id].title) == len("a" * 200)


class TestReply:
    @pytest.fixture(name="case_id")
    def case_id_fixture(self, service):
        return service.receive_email(_email(subject="Pytanie")).case_id

    def test_goes_to_the_sender_with_the_case_number_and_waits(
        self, service, world, out, case_id
    ):
        service.reply(actor_id=PIOTR, case_id=case_id, body=" Dziękujemy. ")

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
        assert _messages(out)[-1] == EmailOutPost(
            staff=STAFF[PIOTR], address="ola@example.com"
        )

    def test_answers_the_case_s_own_person_who_wrote_last_not_a_stranger(
        self, service, world, out, case_id
    ):
        reporter = CasePersonDTO(address="Rep@example.com", name="Rep")
        world._update(case_id, people=[OLA, reporter])
        for sender in ("rep@example.com", "stranger@example.com"):
            service.receive_email(
                _email(
                    message_id=f"<{sender}>",
                    from_address=sender,
                    subject=f"[Z-{case_id}]",
                )
            )

        service.reply(actor_id=PIOTR, case_id=case_id, body="Hej")

        assert out.replies[-1]["to"] == "rep@example.com"

    def test_a_long_title_still_files_its_subject(self, service, world, out):
        case_id = world.add_case()
        world._update(case_id, title="t" * 300)

        service.reply(actor_id=PIOTR, case_id=case_id, body="Hej")

        assert len(out.replies[-1]["subject"]) == CASE_EMAIL_LINE_MAX_LENGTH

    @pytest.mark.parametrize("body", ("   ", "x" * (STAFF_REPLY_MAX_LENGTH + 1)))
    def test_refuses_an_empty_or_overlong_reply(self, service, out, case_id, body):
        with pytest.raises(StaffCaseError) as raised:
            service.reply(actor_id=PIOTR, case_id=case_id, body=body)

        assert raised.value.code == StaffCaseErrorCode.INVALID_BODY
        assert out.replies == []

    def test_with_nobody_to_answer_is_refused(self, service, world, out):
        case_id = world.add_case(people=())

        with pytest.raises(StaffCaseError) as raised:
            service.reply(actor_id=PIOTR, case_id=case_id, body="Hej")

        assert raised.value.code == StaffCaseErrorCode.NO_RECIPIENT
        assert out.replies == []


@pytest.mark.parametrize(
    ("people", "senders", "answered"),
    (
        ((OLA,), (), OLA),
        ((), (OLA,), None),
        (
            (OLA, CasePersonDTO(address="rep@example.com", name="Rep")),
            (
                CasePersonDTO(address="x@example.com", name="X"),
                CasePersonDTO(address="REP@example.com", name="Rep R."),
                OLA,
            ),
            CasePersonDTO(address="REP@example.com", name="Rep R."),
        ),
    ),
    ids=("first-of-its-people", "only-strangers", "last-of-its-own-who-wrote"),
)
def test_a_reply_answers_only_the_case_s_own_people(people, senders, answered, world):
    world._update(world.add_case(people=people), senders=list(senders))

    assert reply_target(next(iter(world.cases.values()))) == answered


class TestAssignAndClose:
    def test_hands_a_case_to_staff_and_back_to_nobody(self, service, world):
        case_id = world.add_case()

        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=RADEK)
        assigned = world.cases[case_id].assignee_id
        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=None)

        assert (assigned, world.cases[case_id].assignee_id) == (RADEK, None)

    def test_refuses_someone_not_on_staff(self, service, world):
        case_id = world.add_case()

        with pytest.raises(StaffCaseError) as raised:
            service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=OUTSIDER)

        assert raised.value.code == StaffCaseErrorCode.INVALID_ASSIGNEE
        assert world.cases[case_id].assignee_id is None

    def test_closes_a_case_with_nothing_to_decide(self, service, world):
        case_id = world.add_case(notices=[_notice(status=ACTIONED)])

        service.close(actor_id=PIOTR, case_id=case_id)

        assert world.cases[case_id].status == CaseStatus.CLOSED

    def test_will_not_close_over_an_open_report(self, service, world):
        case_id = world.add_case(reports=[_report()])

        with pytest.raises(StaffCaseError) as raised:
            service.close(actor_id=PIOTR, case_id=case_id)

        assert raised.value.code == StaffCaseErrorCode.UNDECIDED
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
        assert _messages(out)[-1] == DecisionPost(
            staff=StaffMemberDTO(pk=RADEK, name="Radek"),
            status=ACTIONED,
            decision_text="Prośba o telefon do dziecka.",
        )

    def test_when_the_chat_misses_even_one_message_nothing_is_decided(self, world):
        out = Outside(fails=1)
        case_id = world.add_case(reports=[_report(8), _report(9)])

        with pytest.raises(StaffCaseError) as raised:
            _service(world, out).decide(
                actor_id=PIOTR, case_id=case_id, decision=_decision()
            )

        assert raised.value.code == StaffCaseErrorCode.CHAT_UNAVAILABLE
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
        ("account", "code"),
        (
            ("nikt", StaffCaseErrorCode.UNKNOWN_ACCOUNT),
            ("marek", StaffCaseErrorCode.NO_NOTICE),
        ),
    )
    def test_an_account_that_cannot_be_named_stops_the_decision(
        self, service, world, out, account, code
    ):
        has_notice = code == StaffCaseErrorCode.UNKNOWN_ACCOUNT
        case_id = world.add_case(
            reports=[_report()], notices=[_notice()] if has_notice else []
        )

        with pytest.raises(StaffCaseError) as raised:
            service.decide(
                actor_id=PIOTR,
                case_id=case_id,
                decision=_decision(affected_account=account),
            )

        assert raised.value.code == code
        assert (out.removed, out.reports_decided, out.notices_decided) == ([], [], [])

    def test_decided_meanwhile_by_someone_else_posts_no_second_decision(self, world):
        out = DecidedMeanwhile()
        case_id = world.add_case(reports=[_report()], notices=[_notice()])

        with pytest.raises(StaffCaseError) as raised:
            _service(world, out).decide(
                actor_id=PIOTR, case_id=case_id, decision=_decision()
            )

        assert raised.value.code == StaffCaseErrorCode.NOTHING_TO_DECIDE
        assert not world.cases[case_id].decided_by_name
        assert [m.event for m in _messages(out)] == []

    def test_with_everything_decided_there_is_nothing_to_decide(self, service, world):
        case_id = world.add_case(reports=[_report(status=ACTIONED)])

        with pytest.raises(StaffCaseError) as raised:
            service.decide(actor_id=PIOTR, case_id=case_id, decision=_decision())

        assert raised.value.code == StaffCaseErrorCode.NOTHING_TO_DECIDE

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

    def test_previews_the_statement_of_the_verdict(self, service):
        assert service.preview(_decision()) == (
            "actioned: Prośba o telefon do dziecka."
        )


def test_forgets_case_mail_three_years_on(service, world):
    case_id = service.receive_email(_email()).case_id
    world.now = T0 + timedelta(days=1)
    service.reply(actor_id=PIOTR, case_id=case_id, body="Hej")
    retention = CaseMailRetentionService(repository=world)

    forgotten = retention.forget_expired(now=T0 + timedelta(days=3 * 365, hours=1))

    assert (forgotten, [email["body"] for email in world.emails]) == (1, ["Hej"])


@pytest.mark.parametrize(
    ("subject", "number"),
    (
        ("[Z-1234] Ukryliśmy", 1234),
        ("Re: Fwd: [z-7] wynik", 7),
        ("Z-12 bez nawiasów", None),
        ("", None),
    ),
)
def test_finds_the_case_number_in_brackets(subject, number):
    assert subject_reference(subject) == number


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
