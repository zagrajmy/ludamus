from datetime import UTC, datetime

import pytest

from ludamus.mills.event_deletion import EventDeletionService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event_deletion import (
    EventDeletionApprovalDTO,
    EventDeletionStep,
    EventDeletionTargetDTO,
    NotSphereManagerError,
)
from tests.unit.factories import FakeTransaction

SPHERE_ID = 3
OTHER_SPHERE_ID = 4
EVENT_ID = 10
APPROVED_AT = datetime(2026, 11, 1, 12, tzinfo=UTC)


class FakeDeletionRepository:
    def __init__(self, *, managers):
        self.managers = frozenset(managers)
        self.approvals: list[int] = []
        self.deleted_at: datetime | None = None

    def read_event(self, *, sphere_id, event_id):
        if sphere_id != SPHERE_ID or event_id != EVENT_ID or self.deleted_at:
            raise NotFoundError
        return EventDeletionTargetDTO(
            pk=EVENT_ID, name="Retreat", slug="retreat", sphere_domain="s.test"
        )

    def lock_event(self, *, sphere_id, event_id):
        return self.read_event(sphere_id=sphere_id, event_id=event_id)

    def manager_ids(self, sphere_id):
        return self.managers if sphere_id == SPHERE_ID else frozenset()

    def list_approvals(self, event_id):
        assert event_id == EVENT_ID
        return [
            EventDeletionApprovalDTO(
                user_id=user_id, user_name=f"User {user_id}", approved_at=APPROVED_AT
            )
            for user_id in self.approvals
        ]

    def add_approval(self, *, event_id, user_id):
        assert event_id == EVENT_ID
        if user_id not in self.approvals:
            self.approvals.append(user_id)

    def remove_approval(self, *, event_id, user_id):
        assert event_id == EVENT_ID
        self.approvals = [a for a in self.approvals if a != user_id]

    def soft_delete_event(self, *, event_id, at):
        assert event_id == EVENT_ID
        self.deleted_at = at


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def notify_event_deletion_requested(self, notification):
        self.sent.append(notification)


def _service(repository, notifier=None):
    return EventDeletionService(
        transaction=FakeTransaction(),
        repository=repository,
        notifier=notifier or FakeNotifier(),
    )


def _approve(service, user_id, sphere_id=SPHERE_ID):
    return service.approve(sphere_id=sphere_id, event_id=EVENT_ID, user_id=user_id)


class TestApprove:
    def test_a_solo_manager_deletes_at_once(self):
        repository = FakeDeletionRepository(managers={1})

        missing = _approve(_service(repository), 1)

        assert missing == 0
        assert repository.deleted_at is not None

    def test_the_last_missing_approval_deletes_and_not_one_before(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        service = _service(repository)

        missing = [_approve(service, user_id) for user_id in (1, 2)]
        deleted_before_the_last = repository.deleted_at is not None
        missing.append(_approve(service, 3))

        assert missing == [2, 1, 0]
        assert not deleted_before_the_last
        assert repository.deleted_at is not None

    def test_approving_twice_counts_once(self):
        repository = FakeDeletionRepository(managers={1, 2})
        service = _service(repository)

        missing = [_approve(service, 1), _approve(service, 1)]

        assert missing == [1, 1]
        assert repository.deleted_at is None

    def test_a_former_managers_approval_is_not_counted(self):
        repository = FakeDeletionRepository(managers={2, 3})
        repository.approvals = [1]

        missing = _approve(_service(repository), 2)

        assert missing == 1
        assert repository.deleted_at is None

    def test_someone_off_the_team_is_refused_without_a_trace(self):
        repository = FakeDeletionRepository(managers={1, 2})

        with pytest.raises(NotSphereManagerError):
            _approve(_service(repository), 9)

        assert repository.approvals == []

    def test_an_event_of_another_sphere_is_not_found(self):
        repository = FakeDeletionRepository(managers={1})

        with pytest.raises(NotFoundError):
            _approve(_service(repository), 1, sphere_id=OTHER_SPHERE_ID)

        assert repository.approvals == []
        assert repository.deleted_at is None

    def test_only_the_first_approval_tells_the_other_managers(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        notifier = FakeNotifier()
        service = _service(repository, notifier)

        _approve(service, 1)
        _approve(service, 2)

        assert [
            (n.recipient_user_id, n.requester_name, n.approvals_missing)
            for n in notifier.sent
        ] == [(2, "User 1", 2), (3, "User 1", 2), (4, "User 1", 2), (5, "User 1", 2)]


class TestWithdraw:
    def test_withdrawing_takes_the_approval_back(self):
        repository = FakeDeletionRepository(managers={1, 2})
        repository.approvals = [1]

        _service(repository).withdraw(sphere_id=SPHERE_ID, event_id=EVENT_ID, user_id=1)

        assert repository.approvals == []

    def test_someone_off_the_team_cannot_withdraw_anything(self):
        repository = FakeDeletionRepository(managers={1, 2})
        repository.approvals = [1]

        with pytest.raises(NotSphereManagerError):
            _service(repository).withdraw(
                sphere_id=SPHERE_ID, event_id=EVENT_ID, user_id=9
            )

        assert repository.approvals == [1]


class TestReadBallot:
    @staticmethod
    def _next_step(repository, viewer_id):
        ballot = _service(repository).read_ballot(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, viewer_id=viewer_id
        )
        return ballot.next_step, ballot.missing_after_viewer

    def test_the_first_manager_requests_and_the_others_are_asked(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})

        assert self._next_step(repository, 1) == (EventDeletionStep.REQUEST, 2)

    def test_a_later_manager_approves_while_more_are_needed(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        repository.approvals = [1]

        assert self._next_step(repository, 2) == (EventDeletionStep.APPROVE, 1)

    def test_the_manager_whose_approval_completes_the_count_deletes(self):
        repository = FakeDeletionRepository(managers={1, 2, 3})
        repository.approvals = [1]

        assert self._next_step(repository, 2) == (EventDeletionStep.DELETE, 0)

    def test_a_manager_who_approved_waits_and_may_withdraw(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        repository.approvals = [1]

        assert self._next_step(repository, 1) == (EventDeletionStep.WITHDRAW, 1)

    def test_a_count_met_after_managers_left_lets_an_approver_finish_it(self):
        repository = FakeDeletionRepository(managers={1, 2})
        repository.approvals = [1, 2]

        assert self._next_step(repository, 1) == (EventDeletionStep.DELETE, 0)

    def test_someone_off_the_team_only_watches(self):
        repository = FakeDeletionRepository(managers={1, 2})
        repository.approvals = [1]

        assert self._next_step(repository, 9) == (EventDeletionStep.WATCH, 0)
