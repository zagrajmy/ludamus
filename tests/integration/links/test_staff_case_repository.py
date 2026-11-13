"""StaffCaseRepository against the database.

What could go wrong, and so what the tests below check:
- a thread keeps someone no longer staff, or brings back someone who left
  without marking them active; an unchanged thread is reported as changed;
- the sync reaches a conversation that is not a case's thread;
- a case gets two threads when two requests open it at once;
- a reply goes to someone other than whoever last wrote in, or the reporter;
- a case with a teen in its reported conversation is not seen as one;
- the case shows another case's records, or a decision none of its records hold;
- an ambiguous account identifier picks one of several people.
"""

from datetime import timedelta

from django.utils import timezone

from ludamus.links.db.django.models import (
    CaseEmail,
    ContentNotice,
    ModerationCase,
    ParleyConversation,
    ParleyConversationMember,
    ParleyReport,
)
from ludamus.links.db.django.parley_conversations import ParleyConversationRepository
from ludamus.links.db.django.staff_cases import StaffCaseRepository
from ludamus.pacts.moderation import (
    ModerationDecision,
    ModerationGround,
    ModerationStatus,
    NoticeCategory,
)
from ludamus.pacts.parley import ParleyConversationKind, ParleyMemberState
from ludamus.pacts.staff_cases import CaseStatus, CaseVerdictDTO
from ludamus.pacts.user import AgeBand
from tests.integration.conftest import SphereFactory, UserFactory

ACTIVE, LEFT = ParleyMemberState.ACTIVE, ParleyMemberState.LEFT


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
        case = ModerationCase.objects.create(title="Spam")

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


class TestRead:
    def test_answers_whoever_wrote_in_last(self):
        case = ModerationCase.objects.create()
        _notice(case)
        for address in ("first@example.com", "last@example.com"):
            CaseEmail.objects.create(
                case=case,
                direction=CaseEmail.Direction.IN,
                message_id=f"<{address}>",
                address=address,
                name="Last",
            )
        CaseEmail.objects.create(
            case=case,
            direction=CaseEmail.Direction.OUT,
            message_id="sent",
            address="last@example.com",
        )

        read = StaffCaseRepository.read(case.pk)

        assert (read.reply_to, read.reply_name) == ("last@example.com", "Last")

    def test_falls_back_to_the_notice_then_the_chat_reporter(self):
        noticed = ModerationCase.objects.create()
        _notice(noticed, reporter_email="", reporter_name="")
        _notice(noticed)
        reported = ModerationCase.objects.create()
        _report(reported)
        nobody = ModerationCase.objects.create()

        cases = [StaffCaseRepository.read(c.pk) for c in (noticed, reported, nobody)]

        assert [(case.reply_to, case.reply_name, case.title) for case in cases] == [
            ("ola@example.com", "Ola W.", "Obraźliwy opis"),
            ("reporter@example.com", "Reporter", "Spam"),
            ("", "", ""),
        ]

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

        read = StaffCaseRepository.read(case.pk)

        assert read.title == "Z maila"
        assert len(read.notices) == 1
        assert read.verdict == CaseVerdictDTO(
            status=ModerationStatus.ACTIONED,
            decision=ModerationDecision.CONTENT_REMOVED,
            ground=ModerationGround.TERMS_UNLAWFUL_CONTENT,
            decision_text="Usunięte.",
        )
        (chat,) = read.chat_reports
        assert (chat.pk, chat.involves_minor, chat.author_name) == (
            report.pk,
            True,
            teen.get_full_name(),
        )

    def test_a_rejected_report_reads_as_a_decision_without_ground(self):
        case = ModerationCase.objects.create()
        _report(
            case,
            status=ModerationStatus.REJECTED,
            decision=ModerationDecision.NO_ACTION,
            decision_text="Bez naruszenia.",
        )

        assert StaffCaseRepository.read(case.pk).verdict == CaseVerdictDTO(
            status=ModerationStatus.REJECTED,
            decision=ModerationDecision.NO_ACTION,
            ground=None,
            decision_text="Bez naruszenia.",
        )


class TestList:
    def test_lists_one_state_newest_first_with_a_teen_in_the_conversation(self):
        older = ModerationCase.objects.create()
        newer = ModerationCase.objects.create()
        ModerationCase.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        conversation = ParleyConversation.objects.create(
            kind=ParleyConversationKind.PARTY
        )
        ParleyConversationMember.objects.create(
            conversation=conversation,
            user=UserFactory(age_band=AgeBand.THIRTEEN_TO_FIFTEEN),
            state=ACTIVE,
        )
        _report(newer, sphere=None, conversation=conversation, room_id="conversation:1")
        _notice(older, category=NoticeCategory.CHILD_SAFETY)
        ModerationCase.objects.create(status=CaseStatus.CLOSED)

        rows = StaffCaseRepository.list_cases(CaseStatus.OPEN)

        assert [
            (row.pk, row.involves_minor, row.notice_categories) for row in rows
        ] == [(newer.pk, True, []), (older.pk, False, [NoticeCategory.CHILD_SAFETY])]
        assert StaffCaseRepository.count_by_status() == {
            CaseStatus.OPEN: 2,
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
