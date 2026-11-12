"""StaffCaseRepository against the database.

What could go wrong, and so what the tests below check:
- a thread keeps someone no longer staff, or brings back someone who left
  without marking them active;
- an unchanged thread is reported as changed, so every inbox visit resends it;
- the sync reaches a conversation that is not a case's thread;
- the Worker's member list for a case's thread names someone not on staff.
"""

from ludamus.links.db.django.models import ParleyConversation, ParleyConversationMember
from ludamus.links.db.django.parley_conversations import ParleyConversationRepository
from ludamus.links.db.django.staff_cases import StaffCaseRepository
from ludamus.pacts.parley import ParleyConversationKind, ParleyMemberState
from tests.integration.conftest import UserFactory

ACTIVE, LEFT = ParleyMemberState.ACTIVE, ParleyMemberState.LEFT


def _states(conversation_id):
    return dict(
        ParleyConversationMember.objects.filter(
            conversation_id=conversation_id
        ).values_list("user_id", "state")
    )


def test_threads_follow_who_is_staff_and_say_which_changed():
    piotr, radek, former = (UserFactory(is_staff=True) for _ in range(3))
    repository = StaffCaseRepository()
    first = repository.create_thread("Z-1")
    second = repository.create_thread("Z-2")
    repository.set_thread_members(user_ids=[piotr.pk, former.pk], conversation_ids=None)
    ParleyConversationMember.objects.filter(
        conversation_id=second, user_id=piotr.pk
    ).update(state=LEFT)

    changed = repository.set_thread_members(
        user_ids=[piotr.pk, radek.pk], conversation_ids=None
    )
    again = repository.set_thread_members(
        user_ids=[piotr.pk, radek.pk], conversation_ids=None
    )

    assert (changed, again) == ([first, second], [])
    expected = {piotr.pk: ACTIVE, radek.pk: ACTIVE, former.pk: LEFT}
    assert (_states(first), _states(second)) == (expected, expected)


def test_leaves_other_conversations_alone():
    staff = UserFactory(is_staff=True)
    group = ParleyConversation.objects.create(kind=ParleyConversationKind.GROUP)

    changed = StaffCaseRepository().set_thread_members(
        user_ids=[staff.pk], conversation_ids=[group.pk]
    )

    assert changed == []
    assert not _states(group.pk)


def test_the_member_list_names_only_staff():
    staff = UserFactory(is_staff=True)
    demoted = UserFactory(is_staff=True)
    repository = StaffCaseRepository()
    thread = repository.create_thread("Z-1")
    repository.set_thread_members(
        user_ids=[staff.pk, demoted.pk], conversation_ids=[thread]
    )
    demoted.is_staff = False
    demoted.save()

    kind, members = ParleyConversationRepository.snapshot(thread)

    assert (kind, [member.user_id for member in members]) == (
        ParleyConversationKind.STAFF,
        [staff.pk],
    )
