"""Properties of waiting-list promotion, checked against the real code.

`select_promotable_parties` decides who gets a freed seat. Each property below
is a business rule stated on its own, not a second copy of the walk, so a
change to the walk that breaks a rule fails here whatever the example tests
happen to cover. `HYPOTHESIS_PROFILE=crosshair` runs the same properties
through CrossHair's solver instead of random examples.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from hypothesis import example, given
from hypothesis import strategies as st

from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    PromotionStateDTO,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode
from ludamus.specs.enrollment import select_promotable_parties

_BASE = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
_USERS = range(1, 7)


def _member(
    user_id: int, *, order: int, slots: int = UNLIMITED_SLOTS
) -> WaitingParticipantDTO:
    return WaitingParticipantDTO(
        participation_id=100 + order,
        user_id=user_id,
        sponsor_id=None,
        full_name=f"user-{user_id}",
        email=f"u{user_id}@example.com",
        creation_time=_BASE + timedelta(minutes=order),
        has_conflict=False,
        owner_slots_remaining=slots,
        recipient_user_id=user_id,
    )


def _state(waiting: list[WaitingParticipantDTO], *, seats: int) -> PromotionStateDTO:
    return PromotionStateDTO(
        session_id=1,
        session_title="S",
        event_slug="ev",
        start_time=_BASE + timedelta(days=7),
        promotion_mode=PromotionMode.AUTO,
        offer_claim_window=timedelta(hours=24),
        presenter_id=None,
        available_seats=seats,
        waiting=waiting,
    )


@st.composite
def promotion_states(draw: st.DrawFn) -> PromotionStateDTO:
    user_ids = draw(st.lists(st.sampled_from(_USERS), unique=True, max_size=6))
    slots = draw(
        st.dictionaries(
            st.sampled_from(_USERS),
            st.sampled_from([0, 1, 2, 3, UNLIMITED_SLOTS]),
            min_size=len(_USERS),
            max_size=len(_USERS),
        )
    )
    waiting = []
    for order, user_id in enumerate(user_ids):
        sponsor_id = draw(
            st.none() | st.sampled_from([u for u in _USERS if u != user_id])
        )
        recipient = sponsor_id if sponsor_id is not None else user_id
        waiting.append(
            WaitingParticipantDTO(
                participation_id=100 + order,
                user_id=user_id,
                party_id=draw(st.none() | st.sampled_from([1, 2])),
                sponsor_id=sponsor_id,
                full_name=f"user-{user_id}",
                email=f"u{user_id}@example.com",
                creation_time=_BASE + timedelta(minutes=order),
                has_conflict=draw(st.booleans()),
                owner_slots_remaining=slots[recipient],
                recipient_user_id=recipient,
            )
        )
    return PromotionStateDTO(
        session_id=1,
        session_title="S",
        event_slug="ev",
        start_time=_BASE + timedelta(days=7),
        promotion_mode=PromotionMode.AUTO,
        offer_claim_window=timedelta(hours=24),
        presenter_id=draw(st.none() | st.sampled_from(_USERS)),
        available_seats=draw(st.integers(min_value=0, max_value=6)),
        waiting=waiting,
        shadowbanned_user_ids=frozenset(
            draw(st.sets(st.sampled_from(_USERS), max_size=2))
        ),
    )


def _eligible(state: PromotionStateDTO, member: WaitingParticipantDTO) -> bool:
    return (
        member.user_id != state.presenter_id
        and not member.has_conflict
        and member.user_id not in state.shadowbanned_user_ids
    )


def _eligible_parties(state: PromotionStateDTO) -> list[list[WaitingParticipantDTO]]:
    groups: dict[tuple[str, int], list[WaitingParticipantDTO]] = {}
    for member in state.waiting:
        groups.setdefault(member.promotion_group_key, []).append(member)
    parties = [[m for m in group if _eligible(state, m)] for group in groups.values()]
    return [party for party in parties if party]


def _ids(party: list[WaitingParticipantDTO]) -> list[int]:
    return [member.participation_id for member in party]


def _initial_slots(state: PromotionStateDTO) -> dict[int, int]:
    slots: dict[int, int] = {}
    for member in state.waiting:
        slots.setdefault(member.recipient_user_id, member.owner_slots_remaining)
    return slots


@given(promotion_states())
def test_never_seats_more_than_the_seats_left(state):
    selected = select_promotable_parties(state)

    assert sum(len(party) for party in selected) <= state.available_seats


@given(promotion_states())
def test_promotes_whole_eligible_parties_only(state):
    selected = select_promotable_parties(state)

    eligible = [_ids(party) for party in _eligible_parties(state)]
    assert all(_ids(party) in eligible for party in selected)


@given(promotion_states())
def test_never_spends_more_slots_than_an_owner_has(state):
    selected = select_promotable_parties(state)

    spent = Counter(m.recipient_user_id for party in selected for m in party)
    slots = _initial_slots(state)
    assert all(count <= slots[owner] for owner, count in spent.items())


@given(promotion_states())
# The head of the line has no slots left, so the seat goes to the next party.
@example(_state([_member(1, order=0, slots=0), _member(2, order=1)], seats=1))
def test_passes_over_a_party_only_when_its_owner_is_out_of_slots(state):
    selected = [_ids(party) for party in select_promotable_parties(state)]
    parties = _eligible_parties(state)
    if not selected:
        return
    last = next(i for i, party in enumerate(parties) if _ids(party) == selected[-1])

    remaining = _initial_slots(state)
    for party in parties[:last]:
        if _ids(party) in selected:
            for member in party:
                remaining[member.recipient_user_id] -= 1
            continue
        needed = Counter(m.recipient_user_id for m in party)
        short = [owner for owner, n in needed.items() if n > remaining[owner]]
        assert short, f"party {_ids(party)} fits but was passed over"
        assert all(remaining[owner] <= 0 for owner in short)


@given(promotion_states())
def test_promotes_the_head_of_the_line_when_it_fits(state):
    if not (parties := _eligible_parties(state)):
        return
    head = parties[0]
    needed: dict[int, int] = defaultdict(int)
    for member in head:
        needed[member.recipient_user_id] += 1
    slots = _initial_slots(state)
    fits = len(head) <= state.available_seats and all(
        n <= slots[owner] for owner, n in needed.items()
    )

    selected = select_promotable_parties(state)

    assert (bool(selected) and _ids(selected[0]) == _ids(head)) == fits
