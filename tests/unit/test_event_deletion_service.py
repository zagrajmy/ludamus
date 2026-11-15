from datetime import UTC, datetime

import pytest

from ludamus.mills.event_deletion import EventDeletionService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event_deletion import (
    EventDeletionApprovalDTO,
    EventDeletionOutcome,
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

    def read_event(self, *, sphere_id, event_id, for_update):
        if sphere_id != SPHERE_ID or event_id != EVENT_ID or self.deleted_at:
            raise NotFoundError
        return EventDeletionTargetDTO(
            pk=EVENT_ID, name="Retreat", slug="retreat", sphere_domain="s.test"
        )

    def manager_ids(self, sphere_id):
        return self.managers if sphere_id == SPHERE_ID else frozenset()

    @staticmethod
    def user_name(user_id):
        return f"User {user_id}"

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

        outcome = _approve(_service(repository), 1)

        assert outcome is EventDeletionOutcome.DELETED
        assert repository.deleted_at is not None

    def test_the_last_missing_approval_deletes_and_not_one_before(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        service = _service(repository)

        outcomes = [_approve(service, user_id) for user_id in (1, 2, 3)]

        assert outcomes == [
            EventDeletionOutcome.PENDING,
            EventDeletionOutcome.PENDING,
            EventDeletionOutcome.DELETED,
        ]

    def test_approving_twice_counts_once(self):
        repository = FakeDeletionRepository(managers={1, 2})
        service = _service(repository)

        outcomes = [_approve(service, 1), _approve(service, 1)]

        assert outcomes == [EventDeletionOutcome.PENDING] * 2
        assert repository.deleted_at is None

    def test_a_former_managers_approval_is_not_counted(self):
        repository = FakeDeletionRepository(managers={2, 3})
        repository.approvals = [1]

        outcome = _approve(_service(repository), 2)

        assert outcome is EventDeletionOutcome.PENDING
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
    def _ballot(repository, viewer_id):
        return _service(repository).read_ballot(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, viewer_id=viewer_id
        )

    def test_the_viewer_whose_approval_completes_the_count_is_told_so(self):
        repository = FakeDeletionRepository(managers={1, 2, 3})
        repository.approvals = [1]

        ballot = self._ballot(repository, 2)

        assert (
            ballot.approvals_needed,
            ballot.approvals_missing,
            ballot.viewer_approval_deletes,
            ballot.missing_after_viewer,
        ) == (2, 1, True, 0)

    def test_a_viewer_who_approved_waits_for_the_others(self):
        repository = FakeDeletionRepository(managers={1, 2, 3, 4, 5})
        repository.approvals = [1]

        ballot = self._ballot(repository, 1)

        assert (
            ballot.viewer_has_approved,
            ballot.viewer_approval_deletes,
            ballot.approvals_missing,
        ) == (True, False, 2)

    def test_a_viewer_off_the_team_sees_the_count_but_cannot_act(self):
        repository = FakeDeletionRepository(managers={1, 2})
        repository.approvals = [1]

        ballot = self._ballot(repository, 9)

        assert (
            ballot.viewer_is_manager,
            ballot.viewer_approval_deletes,
            [a.user_id for a in ballot.approvals],
        ) == (False, False, [1])
