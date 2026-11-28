"""Rules of the event deletion vote, checked against `decide_approval`.

Each property states one rule the vote keeps for every team and every stored
approval. `HYPOTHESIS_PROFILE=crosshair` solves for a counterexample instead of
drawing random ones.
"""

from dataclasses import replace

from hypothesis import example, given
from hypothesis import strategies as st

from ludamus.pacts.ids import UserId
from ludamus.specs.event_deletion import (
    Ballot,
    Deleted,
    Recorded,
    Refused,
    Requested,
    approvals_needed,
    decide_approval,
)

_USERS = [UserId(user_id) for user_id in range(1, 10)]
_user_ids = st.sampled_from(_USERS)


@st.composite
def ballots(draw: st.DrawFn) -> Ballot:
    return Ballot(
        managers=frozenset(draw(st.sets(_user_ids, max_size=8))),
        approvers=tuple(draw(st.lists(_user_ids, unique=True, max_size=9))),
    )


def _ballot(*, managers: set[int], approvers: tuple[int, ...] = ()) -> Ballot:
    return Ballot(
        managers=frozenset(UserId(user_id) for user_id in managers),
        approvers=tuple(UserId(user_id) for user_id in approvers),
    )


def _approving_managers(ballot: Ballot) -> set[UserId]:
    return set(ballot.approvers) & ballot.managers


@given(ballots(), _user_ids)
@example(_ballot(managers={1, 2}, approvers=(1,)), UserId(9))
def test_someone_off_the_team_is_refused(ballot, user_id):
    decision = decide_approval(ballot, user_id)

    assert isinstance(decision, Refused) == (user_id not in ballot.managers)


@given(ballots(), _user_ids)
@example(_ballot(managers={1, 2, 3}, approvers=(1,)), UserId(2))
@example(_ballot(managers={1, 2, 3, 4, 5}, approvers=(1,)), UserId(2))
def test_the_event_is_deleted_exactly_when_enough_managers_approve(ballot, user_id):
    decision = decide_approval(ballot, user_id)

    approving = _approving_managers(ballot) | ({user_id} & ballot.managers)
    quorum = user_id in ballot.managers and len(approving) >= approvals_needed(
        len(ballot.managers)
    )
    assert isinstance(decision, Deleted) == quorum


@given(ballots(), _user_ids)
@example(_ballot(managers={1, 2}), UserId(1))
@example(_ballot(managers={1, 2}, approvers=(1,)), UserId(1))
def test_no_one_in_a_team_deletes_alone(ballot, user_id):
    decision = decide_approval(ballot, user_id)

    alone = len(ballot.managers) > 1 and not _approving_managers(ballot) - {user_id}
    assert not (alone and isinstance(decision, Deleted))


@given(ballots(), _user_ids)
@example(_ballot(managers={2, 3}, approvers=(1,)), UserId(2))
def test_a_former_managers_approval_changes_nothing(ballot, user_id):
    without_former = replace(
        ballot, approvers=tuple(a for a in ballot.approvers if a in ballot.managers)
    )

    assert decide_approval(ballot, user_id) == decide_approval(without_former, user_id)


@given(ballots(), _user_ids)
@example(_ballot(managers={1, 2, 3, 4, 5}), UserId(1))
@example(_ballot(managers={1, 2, 3, 4, 5}, approvers=(1,)), UserId(2))
def test_only_the_first_approval_asks_and_it_asks_every_other_manager(ballot, user_id):
    decision = decide_approval(ballot, user_id)

    if isinstance(decision, Requested):
        assert not _approving_managers(ballot)
        assert decision.recipients == ballot.managers - {user_id}
    elif isinstance(decision, Recorded):
        assert _approving_managers(ballot)


@given(ballots(), _user_ids)
@example(_ballot(managers={1, 2}), UserId(1))
def test_approving_again_neither_asks_again_nor_moves_the_count(ballot, user_id):
    first = decide_approval(ballot, user_id)
    again = decide_approval(
        replace(ballot, approvers=(*ballot.approvers, user_id)), user_id
    )

    if isinstance(first, (Recorded, Requested)):
        assert again == Recorded(missing=first.missing)
    else:
        assert again == first


@given(ballots(), _user_ids)
def test_the_missing_count_is_what_the_quorum_still_lacks(ballot, user_id):
    decision = decide_approval(ballot, user_id)

    if isinstance(decision, (Recorded, Requested)):
        approving = _approving_managers(ballot) | {user_id}
        assert decision.missing == approvals_needed(len(ballot.managers)) - len(
            approving
        )
        assert decision.missing > 0
