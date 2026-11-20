import pytest

from ludamus.specs.event_deletion import approvals_needed


@pytest.mark.parametrize(
    ("manager_count", "needed"),
    ((1, 1), (2, 2), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4), (20, 4)),
)
def test_approvals_needed_follows_the_agreed_table(manager_count, needed):
    assert approvals_needed(manager_count) == needed


def test_no_managers_means_no_one_can_approve():
    assert approvals_needed(0) == 0
