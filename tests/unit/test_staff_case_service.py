"""StaffCaseService against an in-memory world.

What could go wrong, and so what the tests below check:
- someone not on staff reads or changes a case;
- a child-safety case sinks below newer ones in the inbox;
- a case's thread keeps someone no longer on staff, or misses someone new,
  or every inbox visit resends every thread's members;
- a chat report opens a second case, or a case for a report that is not there;
- a redelivered email files twice, or posts twice into the thread;
- an email naming a case lands in a new one, or one naming no case that exists
  is dropped; a reply to a waiting or closed case leaves it there;
- a note reaches the outside, or a reply by email goes nowhere, to the wrong
  person, or without the case number in its subject;
- a case is handed to someone not on staff;
- the person who decided also decides the appeal.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ludamus.mills.parley_conversations import visible_conversations
from ludamus.mills.staff_cases import (
    StaffCaseService,
    may_decide,
    reply_subject,
    subject_reference,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.parley import (
    ParleyConversationDTO,
    ParleyConversationKind,
    ParleyMemberState,
)
from ludamus.pacts.staff_cases import (
    STAFF_CASE_TITLE_MAX_LENGTH,
    STAFF_REPLY_MAX_LENGTH,
    STAFF_THREAD_POST_MAX_LENGTH,
    ChatReportFacts,
    InboundEmail,
    ModerationAction,
    ModerationGround,
    ReportedContentDTO,
    StaffCaseDecisionDTO,
    StaffCaseDTO,
    StaffCaseError,
    StaffCaseKind,
    StaffCaseListItemDTO,
    StaffCaseStatus,
    StaffEmailDirection,
    StaffEmailOutcome,
    StaffMemberDTO,
    StaffThreadEvent,
)
from ludamus.specs.staff_cases import STAFF_CASE_RETENTION
from tests.unit.factories import FakeTransaction

PIOTR, RADEK, OUTSIDER = 1, 2, 3
T0 = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)


class World:
    def __init__(self) -> None:
        self.staff = {PIOTR: "Piotr", RADEK: "Radek"}
        self.cases: dict[int, StaffCaseDTO] = {}
        self.threads: dict[int, set[int]] = {}
        self.reports: dict[tuple[int, str, int], ChatReportFacts] = {}
        self.emails: list[dict] = []
        self.decisions: list[dict] = []
        self.clock = T0

    def read_staff(self, user_id):
        name = self.staff.get(user_id)
        return None if name is None else StaffMemberDTO(pk=user_id, name=name)

    def list_staff(self):
        return [StaffMemberDTO(pk=pk, name=name) for pk, name in self.staff.items()]

    def create_thread(self, _title):
        conversation_id = 100 + len(self.threads)
        self.threads[conversation_id] = set()
        return conversation_id

    def set_thread_members(self, *, user_ids, conversation_ids):
        changed = []
        for conversation_id in conversation_ids or list(self.threads):
            if self.threads[conversation_id] != set(user_ids):
                self.threads[conversation_id] = set(user_ids)
                changed.append(conversation_id)
        return changed

    def create(self, data):
        self.clock += timedelta(minutes=1)
        pk = 1000 + len(self.cases)
        self.cases[pk] = StaffCaseDTO(
            pk=pk,
            status=StaffCaseStatus.OPEN,
            assignee_id=None,
            notice_id=None,
            decision=None,
            created_at=self.clock,
            **data,
        )
        return self.cases[pk]

    def read(self, case_id):
        if case_id not in self.cases:
            raise NotFoundError
        return self.cases[case_id]

    def read_for_report(self, report_id):
        return next(
            (case for case in self.cases.values() if case.report_id == report_id), None
        )

    def find_chat_report(self, *, reporter_id, room_id, message_id):
        return self.reports.get((reporter_id, room_id, message_id))

    @staticmethod
    def read_content(report_id):
        return ReportedContentDTO(
            room_id="conversation:5",
            message_id=report_id,
            reason="",
            reporter_name="",
            author_id=None,
            author_name="",
            author_age_band=None,
            author_joined_at=None,
            body="",
            written_at=None,
            deleted_at=None,
        )

    def list_cases(self, status):
        return [
            StaffCaseListItemDTO(
                pk=case.pk,
                kind=case.kind,
                status=case.status,
                title=case.title,
                child_safety=case.child_safety,
                assignee_name="",
                created_at=case.created_at,
            )
            for case in self.cases.values()
            if case.status == status
        ]

    def count_by_status(self):
        return {
            status: sum(case.status == status for case in self.cases.values())
            for status in StaffCaseStatus
        }

    def set_status(self, *, case_id, status):
        self.cases[case_id] = self.cases[case_id].model_copy(update={"status": status})

    def set_assignee(self, *, case_id, assignee_id):
        self.cases[case_id] = self.cases[case_id].model_copy(
            update={"assignee_id": assignee_id}
        )

    def email_seen(self, message_id):
        return next(
            (e["case_id"] for e in self.emails if e["message_id"] == message_id), None
        )

    def add_email(self, data):
        self.emails.append(data)

    @staticmethod
    def list_emails(_case_id):
        return []

    def record_decision(self, data):
        self.decisions.append(data)
        decision = StaffCaseDecisionDTO(
            action=data["action"],
            ground=data["ground"],
            decided_by_id=data["decided_by_id"],
            decided_by_name=self.staff[data["decided_by_id"]],
            decided_at=T0,
        )
        case_id = data["case_id"]
        self.cases[case_id] = self.cases[case_id].model_copy(
            update={"decision": decision}
        )
        return decision


class Recorder:
    def __init__(self) -> None:
        self.posts = []
        self.mails = []
        self.synced = []

    def post(self, entry):
        self.posts.append(entry)

    def send(self, **mail):
        self.mails.append(mail)

    def schedule(self, *, conversation_ids):
        self.synced.append(conversation_ids)


@pytest.fixture(name="world")
def world_fixture():
    return World()


@pytest.fixture(name="out")
def out_fixture():
    return Recorder()


@pytest.fixture(name="service")
def service_fixture(world, out):
    return StaffCaseService(
        transaction=FakeTransaction(),
        repository=world,
        thread=out,
        mailer=out,
        memberships=out,
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


def _report(world, *, reporter_id=7, minor=False, email="ola@example.com"):
    facts = ChatReportFacts(
        report_id=len(world.reports) + 1,
        reason="Prosi o telefon",
        reporter_name="Ola W.",
        reporter_email=email,
        room_id="conversation:5",
        involves_minor=minor,
    )
    world.reports[reporter_id, "conversation:5", 42] = facts
    return facts


class TestStaffOnly:
    @pytest.mark.parametrize(
        "call",
        (
            lambda s: s.inbox(actor_id=OUTSIDER, status=StaffCaseStatus.OPEN),
            lambda s: s.read(actor_id=OUTSIDER, case_id=1000),
            lambda s: s.reply(
                actor_id=OUTSIDER, case_id=1000, body="x", by_email=False
            ),
            lambda s: s.assign(actor_id=OUTSIDER, case_id=1000, assignee_id=PIOTR),
            lambda s: s.decide(
                actor_id=OUTSIDER,
                case_id=1000,
                action=ModerationAction.HIDE,
                ground=ModerationGround.RIGHTS,
            ),
        ),
    )
    def test_someone_not_on_staff_finds_nothing(self, service, world, out, call):
        service.receive_email(_email())
        posted = len(out.posts)

        with pytest.raises(NotFoundError):
            call(service)

        assert (len(out.posts), len(world.decisions)) == (posted, 0)


class TestInbox:
    def test_lists_child_safety_first_then_newest_with_counts(self, service, world):
        service.receive_email(_email(message_id="<1>"))
        _report(world, minor=True)
        service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )
        service.receive_email(_email(message_id="<3>", subject="Nowsze"))

        inbox = service.inbox(actor_id=PIOTR, status=StaffCaseStatus.OPEN)

        assert [case.pk for case in inbox.cases] == [1001, 1002, 1000]
        assert inbox.counts == {
            StaffCaseStatus.OPEN: 3,
            StaffCaseStatus.WAITING: 0,
            StaffCaseStatus.CLOSED: 0,
        }

    def test_brings_every_thread_in_step_with_staff_once(self, service, world, out):
        service.receive_email(_email())
        world.staff[4] = "Nowa"
        del world.staff[RADEK]

        service.inbox(actor_id=PIOTR, status=StaffCaseStatus.OPEN)
        service.inbox(actor_id=PIOTR, status=StaffCaseStatus.OPEN)

        assert world.threads == {100: {PIOTR, 4}}
        assert out.synced[-2:] == [[100], []]


class TestChatReport:
    def test_opens_a_case_with_the_reporter_to_answer(self, service, world, out):
        facts = _report(world, minor=True)

        case = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )

        assert case is not None
        assert (case.kind, case.child_safety, case.report_id) == (
            StaffCaseKind.CHAT_REPORT,
            True,
            facts.report_id,
        )
        assert (case.external_email, case.title) == (
            "ola@example.com",
            "Prosi o telefon",
        )
        assert world.threads[case.conversation_id] == {PIOTR, RADEK}
        assert [(p.event, p.author_id, p.retain_for) for p in out.posts] == [
            (StaffThreadEvent.CASE_OPENED, None, STAFF_CASE_RETENTION)
        ]

    def test_reported_again_keeps_its_one_case(self, service, world, out):
        _report(world)
        first = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )

        again = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )

        assert again == first
        assert (len(world.cases), len(out.posts)) == (1, 1)

    def test_no_report_no_case(self, service, world):
        assert (
            service.open_for_chat_report(
                reporter_id=7, room_id="conversation:5", message_id=42
            )
            is None
        )
        assert world.cases == {}


class TestInboundEmail:
    def test_without_a_case_number_opens_one_for_the_sender(self, service, world):
        receipt = service.receive_email(_email(subject="  Naruszenie   w opisie "))

        case = world.cases[receipt.case_id]
        assert receipt.outcome == StaffEmailOutcome.OPENED
        assert (case.kind, case.title, case.external_email, case.external_name) == (
            StaffCaseKind.EMAIL,
            "Naruszenie w opisie",
            "ola@example.com",
            "Ola W.",
        )

    def test_naming_a_case_reopens_it(self, service, world, out):
        _report(world)
        case = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )
        assert case is not None
        world.set_status(case_id=case.pk, status=StaffCaseStatus.CLOSED)

        receipt = service.receive_email(
            _email(subject=f"Re: Fwd: [z-{case.pk}] wynik", attachments=["a.png"])
        )

        assert (receipt.outcome, receipt.case_id) == (
            StaffEmailOutcome.ATTACHED,
            case.pk,
        )
        assert world.cases[case.pk].status == StaffCaseStatus.OPEN
        assert out.posts[-1].details["attachments"] == "1"

    def test_naming_an_open_case_leaves_it_open(self, service, world):
        case_id = service.receive_email(_email()).case_id

        service.receive_email(_email(message_id="<b>", subject=f"[Z-{case_id}]"))

        assert (len(world.cases), world.cases[case_id].status) == (
            1,
            StaffCaseStatus.OPEN,
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
        assert (len(world.emails), len(out.posts)) == (1, 1)

    def test_posts_under_a_nonce_its_message_id_decides(self, service, out):
        service.receive_email(_email(message_id="<x@y>"))
        service.receive_email(_email(message_id="<z@y>"))

        nonces = [post.nonce for post in out.posts]
        assert nonces[0] != nonces[1]
        assert all(nonce.startswith("email-") for nonce in nonces)


class TestReply:
    @pytest.fixture(name="case")
    def case_fixture(self, service, world):
        return world.cases[service.receive_email(_email(subject="Pytanie")).case_id]

    def test_by_email_goes_to_the_sender_with_the_case_number(
        self, service, world, out, case
    ):
        service.reply(
            actor_id=PIOTR, case_id=case.pk, body=" Dziękujemy. ", by_email=True
        )

        assert out.mails == [
            {
                "to": "ola@example.com",
                "subject": f"[Z-{case.pk}] Pytanie",
                "body": "Dziękujemy.",
                "nonce": world.emails[-1]["message_id"],
            }
        ]
        assert (world.emails[-1]["direction"], world.emails[-1]["sent_by_id"]) == (
            StaffEmailDirection.OUT,
            PIOTR,
        )
        assert world.cases[case.pk].status == StaffCaseStatus.WAITING
        assert (out.posts[-1].event, out.posts[-1].author_name) == (
            StaffThreadEvent.EMAIL_OUT,
            "Piotr",
        )

    def test_a_note_stays_in_the_thread(self, service, world, out, case):
        service.reply(actor_id=RADEK, case_id=case.pk, body="Sprawdzam", by_email=False)

        assert (out.mails, len(world.emails)) == ([], 1)
        assert (out.posts[-1].event, out.posts[-1].author_id) == (
            StaffThreadEvent.NOTE,
            RADEK,
        )

    @pytest.mark.parametrize("body", ("   ", "x" * (STAFF_REPLY_MAX_LENGTH + 1)))
    def test_refuses_an_empty_or_overlong_reply(self, service, out, case, body):
        with pytest.raises(StaffCaseError, match="invalid_body"):
            service.reply(actor_id=PIOTR, case_id=case.pk, body=body, by_email=True)

        assert out.mails == []

    def test_by_email_with_nobody_to_answer_is_refused(self, service, world, out):
        _report(world, email="")
        case = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )
        assert case is not None

        with pytest.raises(StaffCaseError, match="no_recipient"):
            service.reply(actor_id=PIOTR, case_id=case.pk, body="Hej", by_email=True)

        assert out.mails == []


class TestAssign:
    def test_hands_a_case_to_staff_and_back_to_nobody(self, service, world):
        case_id = service.receive_email(_email()).case_id

        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=RADEK)
        assigned = world.cases[case_id].assignee_id
        service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=None)

        assert (assigned, world.cases[case_id].assignee_id) == (RADEK, None)

    def test_refuses_someone_not_on_staff(self, service, world):
        case_id = service.receive_email(_email()).case_id

        with pytest.raises(StaffCaseError, match="invalid_assignee"):
            service.assign(actor_id=PIOTR, case_id=case_id, assignee_id=OUTSIDER)

        assert world.cases[case_id].assignee_id is None

    def test_an_unknown_case_is_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.assign(actor_id=PIOTR, case_id=404, assignee_id=None)


class TestDecide:
    def test_records_closes_and_posts_the_decision(self, service, world, out):
        case_id = service.receive_email(_email()).case_id

        decision = service.decide(
            actor_id=PIOTR,
            case_id=case_id,
            action=ModerationAction.MUTE_24H,
            ground=ModerationGround.RIGHTS,
        )

        assert (decision.action, decision.decided_by_id) == (
            ModerationAction.MUTE_24H,
            PIOTR,
        )
        assert world.cases[case_id].status == StaffCaseStatus.CLOSED
        assert out.posts[-1].details == {
            "reference": f"Z-{case_id}",
            "action": ModerationAction.MUTE_24H,
            "ground": ModerationGround.RIGHTS,
        }

    def test_the_appeal_goes_to_someone_else(self, service, world):
        case_id = service.receive_email(_email()).case_id
        service.decide(
            actor_id=PIOTR,
            case_id=case_id,
            action=ModerationAction.HIDE,
            ground=ModerationGround.RIGHTS,
        )

        with pytest.raises(StaffCaseError, match="same_decider"):
            service.decide(
                actor_id=PIOTR,
                case_id=case_id,
                action=ModerationAction.NONE,
                ground=ModerationGround.RIGHTS,
            )
        service.decide(
            actor_id=RADEK,
            case_id=case_id,
            action=ModerationAction.NONE,
            ground=ModerationGround.RIGHTS,
        )

        assert [d["decided_by_id"] for d in world.decisions] == [PIOTR, RADEK]
        assert service.read(actor_id=RADEK, case_id=case_id).may_decide is False


class TestRead:
    def test_brings_the_reported_content_and_who_is_on_staff(self, service, world):
        _report(world)
        case = service.open_for_chat_report(
            reporter_id=7, room_id="conversation:5", message_id=42
        )
        assert case is not None

        detail = service.read(actor_id=RADEK, case_id=case.pk)

        assert detail.content is not None
        assert detail.content.room_id == "conversation:5"
        assert [member.name for member in detail.staff] == ["Piotr", "Radek"]
        assert detail.may_decide is True

    def test_an_email_case_has_no_reported_content(self, service):
        case_id = service.receive_email(_email()).case_id

        assert service.read(actor_id=PIOTR, case_id=case_id).content is None


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

    def test_a_reply_without_a_title_still_names_the_case(self, service, world):
        case_id = service.receive_email(_email(subject="")).case_id

        assert reply_subject(world.cases[case_id]) == f"[Z-{case_id}] (bez tematu)"

    def test_a_long_subject_is_clipped_to_the_title_length(self, service, world):
        case_id = service.receive_email(_email(subject="a" * 500)).case_id

        title = world.cases[case_id].title
        assert (len(title), title[-1]) == (STAFF_CASE_TITLE_MAX_LENGTH, "…")

    def test_a_long_email_is_clipped_for_the_thread(self, service, out):
        service.receive_email(_email(body="b" * 10_000))

        assert len(out.posts[-1].body) == STAFF_THREAD_POST_MAX_LENGTH


def test_may_decide_a_case_nobody_decided():
    case = StaffCaseDTO(
        pk=1,
        kind=StaffCaseKind.NOTICE,
        status=StaffCaseStatus.OPEN,
        title="",
        child_safety=False,
        assignee_id=None,
        conversation_id=1,
        external_email="",
        external_name="",
        report_id=None,
        notice_id=None,
        decision=None,
        created_at=T0,
    )

    assert may_decide(case, PIOTR) is True


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
