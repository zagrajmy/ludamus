import pytest

from ludamus.pacts.event_deletion import EventDeletionStep
from ludamus.pacts.ids import UserId
from ludamus.specs.event_deletion import (
    Ballot,
    approvals_needed,
    decide_approval,
    next_step,
)


@pytest.mark.parametrize(
    ("manager_count", "needed"),
    ((1, 1), (2, 2), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4), (20, 4)),
)
def test_approvals_needed_follows_the_agreed_table(manager_count, needed):
    assert approvals_needed(manager_count) == needed


def test_no_managers_means_no_one_can_approve():
    assert approvals_needed(0) == 0


@pytest.mark.parametrize(
    ("managers", "approvers", "viewer_id", "step"),
    (
        pytest.param({1, 2, 3, 4, 5}, (), 1, EventDeletionStep.REQUEST, id="first"),
        pytest.param({1, 2, 3, 4, 5}, (1,), 2, EventDeletionStep.APPROVE, id="later"),
        pytest.param({1, 2, 3}, (1,), 2, EventDeletionStep.DELETE, id="last"),
        pytest.param(
            {1, 2, 3, 4, 5}, (1,), 1, EventDeletionStep.WITHDRAW, id="approved"
        ),
        pytest.param(
            {1, 2}, (1, 2), 1, EventDeletionStep.DELETE, id="met-after-leavers"
        ),
        pytest.param({1, 2}, (1,), 9, EventDeletionStep.WATCH, id="off-the-team"),
    ),
)
def test_next_step_names_what_the_viewers_approval_would_do(
    managers, approvers, viewer_id, step
):
    ballot = Ballot(
        managers=frozenset(UserId(user_id) for user_id in managers),
        approvers=frozenset(UserId(user_id) for user_id in approvers),
    )

    assert next_step(decide_approval(ballot, UserId(viewer_id))) == step
