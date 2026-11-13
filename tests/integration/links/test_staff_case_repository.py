"""StaffCaseRepository against the database.

What could go wrong, and so what the tests below check:
- a thread keeps someone no longer staff, or brings back someone who left
  without marking them active; an unchanged thread is reported as changed;
- the sync reaches a conversation that is not a case's thread;
- a case gets two threads when two requests open it at once;
- a reply goes to a stranger who put "[Z-n]" in a subject, rather than to the
  case's own people;
- a case with an urgent notice or a teen in its reported conversation is not
  marked as child safety, or sinks below a newer one;
- a case is named by the wrong kind, or shows a decision none of its records hold;
- an ambiguous account identifier picks one of several people;
- someone made staff in the admin stays out of the case threads.
"""

from datetime import datetime, timedelta

from django.urls import reverse
from django.utils import timezone
from zeal import zeal_ignore

from ludamus.links.db.django.models import (
    CaseEmail,
    ContentNotice,
    ModerationCase,
    ParleyConversation,
    ParleyConversationMember,
    ParleyReport,
    StatementOfReasons,
)
from ludamus.links.db.django.parley_conversations import ParleyConversationRepository
from ludamus.links.db.django.staff_cases import StaffCaseRepository
from ludamus.pacts.moderation import (
    CaseStatus,
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    NoticeCategory,
)
from ludamus.pacts.parley import ParleyConversationKind, ParleyMemberState
from ludamus.pacts.staff_cases import CaseKind, CaseVerdictDTO
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import SphereFactory, UserFactory

ACTIVE, LEFT = ParleyMemberState.ACTIVE, ParleyMemberState.LEFT
URGENT = frozenset({NoticeCategory.CHILD_SAFETY})


def _states(thread_id):
    return dict(
        ParleyConversationMember.objects.filter(conversation_id=thread_id).values_list(
            "user_id", "state"
        )
    )


def _notice(case, **overrides):
    return ContentNotice.objects.create(
        **{
            "case": case,
            "url": "https://zagrajmy.net/e/abc/",
            "category": NoticeCategory.HARASSMENT,
            "explanation": "Obraźliwy opis",
            "reporter_name": "Ola W.",
            "reporter_email": "ola@example.com",
            "language": "pl",
            **overrides,
        }
    )


def _report(case, **overrides):
    return ParleyReport.objects.create(
        **{
            "case": case,
            "sphere": SphereFactory(),
            "reporter": UserFactory(email="reporter@example.com", name="Reporter"),
            "room_id": "organizers:1",
            "message_id": 7,
            "reason": "Spam",
            **overrides,
        }
    )


def _mail_in(case, address, *, name="", message_id=None):
    CaseEmail.objects.create(
        case=case,
        direction=CaseEmail.Direction.IN,
        message_id=message_id or f"<{address}>",
        address=address,
        name=name,
    )


def _read(case):
    return StaffCaseRepository.read(case.pk, urgent=URGENT)


class TestThreads:
    def test_follow_who_is_staff_and_say_which_changed(self):
        piotr, radek, former = (UserFactory(is_staff=True) for _ in range(3))
        repository = StaffCaseRepository()
        first = repository.open_thread(ModerationCase.objects.create().pk)
        second = repository.open_thread(ModerationCase.objects.create().pk)
        repository.set_thread_members(user_ids=[piotr.pk, former.pk], thread_ids=None)
        ParleyConversationMember.objects.filter(
            conversation_id=second, user_id=piotr.pk
        ).update(state=LEFT)

        changed = repository.set_thread_members(
            user_ids=[piotr.pk, radek.pk], thread_ids=None
        )
        again = repository.set_thread_members(
            user_ids=[piotr.pk, radek.pk], thread_ids=None
        )

        assert (changed, again) == ([first, second], [])
        expected = {piotr.pk: ACTIVE, radek.pk: ACTIVE, former.pk: LEFT}
        assert (_states(first), _states(second)) == (expected, expected)

    def test_leave_other_conversations_alone(self):
        staff = UserFactory(is_staff=True)
        group = ParleyConversation.objects.create(kind=ParleyConversationKind.GROUP)

        changed = StaffCaseRepository.set_thread_members(
            user_ids=[staff.pk], thread_ids=[group.pk]
        )

        assert changed == []
        assert not _states(group.pk)

    def test_a_case_keeps_the_thread_it_got_first(self):
        case = ModerationCase.objects.create()
        _report(case)

        first = StaffCaseRepository.open_thread(case.pk)
        second = StaffCaseRepository.open_thread(case.pk)

        assert first == second
        assert list(
            ParleyConversation.objects.filter(
                kind=ParleyConversationKind.STAFF
            ).values_list("pk", "title")
        ) == [(first, f"Z-{case.pk} Spam")]

    def test_the_member_list_says_who_is_staff(self):
        staff, demoted = UserFactory(is_staff=True), UserFactory(is_staff=True)
        thread = StaffCaseRepository.open_thread(ModerationCase.objects.create().pk)
        StaffCaseRepository.set_thread_members(
            user_ids=[staff.pk, demoted.pk], thread_ids=[thread]
        )
        demoted.is_staff = False
        demoted.save()

        kind, members = ParleyConversationRepository.snapshot(thread)

        assert (kind, {m.user_id: m.is_staff for m in members}) == (
            ParleyConversationKind.STAFF,
            {staff.pk: True, demoted.pk: False},
        )


class TestReplyTo:
    def test_answers_the_last_of_the_case_s_own_people_who_wrote_in(self):
        case = ModerationCase.objects.create()
        _notice(case)
        author = UserFactory(email="author@example.com")
        StatementOfReasons.objects.create(
            case=case,
            user=author,
            decision=ModerationDecision.CONTENT_REMOVED,
            ground=ModerationGround.TERMS_OTHERS_RIGHTS,
            facts="x",
            from_report=True,
        )
        _mail_in(case, "OLA@example.com", name="Ola")
        _mail_in(case, "author@example.com", name="Author")
        _mail_in(case, "stranger@example.com", name="Stranger")

        read = _read(case)

        assert (read.reply_to, read.reply_name) == ("author@example.com", "Author")

    def test_a_stranger_naming_the_case_is_never_answered(self):
        case = ModerationCase.objects.create()
        _report(case)
        _mail_in(case, "stranger@example.com")

        assert _read(case).reply_to == "reporter@example.com"

    def test_falls_back_to_the_sender_the_notice_then_the_chat_reporter(self):
        emailed = ModerationCase.objects.create(
            title="Z maila", external_email="ola@example.com", external_name="Ola"
        )
        noticed = ModerationCase.objects.create()
        _notice(noticed, reporter_email="", reporter_name="")
        _notice(noticed)
        reported = ModerationCase.objects.create()
        _report(reported)
        nobody = ModerationCase.objects.create()

        cases = [_read(c) for c in (emailed, noticed, reported, nobody)]

        assert [(c.reply_to, c.reply_name, c.title, c.kind) for c in cases] == [
            ("ola@example.com", "Ola", "Z maila", CaseKind.EMAIL),
            ("ola@example.com", "Ola W.", "Obraźliwy opis", CaseKind.NOTICE),
            ("reporter@example.com", "Reporter", "Spam", CaseKind.CHAT_REPORT),
            ("", "", "", CaseKind.STATEMENT),
        ]


class TestRead:
    def test_brings_its_records_and_how_they_were_decided(self):
        case = ModerationCase.objects.create(title="Z maila")
        _notice(
            case,
            status=ModerationStatus.ACTIONED,
            decision=ModerationDecision.CONTENT_REMOVED,
            ground=ModerationGround.TERMS_UNLAWFUL_CONTENT,
            decision_text="Usunięte.",
        )
        _notice(ModerationCase.objects.create())
        teen = UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN)
        report = _report(case, reported_user=teen, author_name="")

        read = _read(case)

        assert (read.title, read.child_safety, len(read.notices)) == (
            "Z maila",
            True,
            1,
        )
        assert read.verdict == CaseVerdictDTO(
            status=ModerationStatus.ACTIONED,
            decision=ModerationDecision.CONTENT_REMOVED,
            ground=ModerationGround.TERMS_UNLAWFUL_CONTENT,
            decision_text="Usunięte.",
        )
        (chat,) = read.chat_reports
        assert (chat.pk, chat.author_name, chat.author_age_band) == (
            report.pk,
            teen.get_full_name(),
            AgeBand.THIRTEEN_TO_FIFTEEN,
        )

    def test_a_rejected_report_reads_as_a_decision_without_ground(self):
        case = ModerationCase.objects.create()
        _report(
            case,
            status=ModerationStatus.REJECTED,
            decision=ModerationDecision.NO_ACTION,
            decision_text="Bez naruszenia.",
        )

        assert _read(case).verdict == CaseVerdictDTO(
            status=ModerationStatus.REJECTED,
            decision=ModerationDecision.NO_ACTION,
            ground=None,
            decision_text="Bez naruszenia.",
        )


class TestList:
    def test_puts_child_safety_first_then_the_newest_one_page_at_a_time(self):
        now = timezone.now()
        plain_old, plain_new, urgent, teen_chat = (
            ModerationCase.objects.create() for _ in range(4)
        )
        for age, case in enumerate((teen_chat, urgent, plain_new, plain_old)):
            ModerationCase.objects.filter(pk=case.pk).update(
                created_at=now - timedelta(days=age)
            )
        _notice(plain_old)
        _notice(plain_new)
        _notice(urgent, category=NoticeCategory.CHILD_SAFETY)
        conversation = ParleyConversation.objects.create(
            kind=ParleyConversationKind.PARTY
        )
        ParleyConversationMember.objects.create(
            conversation=conversation,
            user=UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN),
            state=ACTIVE,
        )
        _report(
            teen_chat, sphere=None, conversation=conversation, room_id="conversation:1"
        )
        ModerationCase.objects.create(status=CaseStatus.CLOSED)

        first = StaffCaseRepository.list_cases(
            CaseStatus.OPEN, urgent=URGENT, limit=3, offset=0
        )
        rest = StaffCaseRepository.list_cases(
            CaseStatus.OPEN, urgent=URGENT, limit=3, offset=3
        )

        assert [(row.pk, row.child_safety) for row in first + rest] == [
            (teen_chat.pk, True),
            (urgent.pk, True),
            (plain_new.pk, False),
            (plain_old.pk, False),
        ]
        assert StaffCaseRepository.count_by_status() == {
            CaseStatus.OPEN: 4,
            CaseStatus.WAITING: 0,
            CaseStatus.CLOSED: 1,
        }


def test_names_an_account_only_when_one_matches():
    marek = UserFactory(username="marek", email="marek@example.com")
    UserFactory(username="twin", email="shared@example.com")
    UserFactory(username="shared@example.com")

    assert [
        StaffCaseRepository.find_account(identifier)
        for identifier in ("marek", "MAREK@example.com", "shared@example.com", "nikt")
    ] == [marek.pk, marek.pk, None, None]


def test_making_someone_staff_in_the_admin_brings_them_into_case_threads(client):
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin_user)
    thread = StaffCaseRepository.open_thread(ModerationCase.objects.create().pk)
    StaffCaseRepository.set_thread_members(user_ids=[admin_user.pk], thread_ids=None)
    newcomer = UserFactory()
    url = reverse("admin:db_main_user_change", args=[newcomer.pk])
    with zeal_ignore():
        form = client.get(url).context["adminform"].form
    data = {}
    for name, field in form.fields.items():
        value = form.initial.get(name, field.initial)
        if isinstance(value, datetime):
            data[f"{name}_0"] = value.date().isoformat()
            data[f"{name}_1"] = value.time().strftime("%H:%M:%S")
        elif value is not None and not isinstance(value, (list, tuple)):
            data[name] = value

    client.post(url, data | {"is_staff": "on", "password": "!unusable"})

    assert _states(thread) == {admin_user.pk: ACTIVE, newcomer.pk: ACTIVE}
