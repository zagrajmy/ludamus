"""Business invariants for waiting-list promotion.

Pure, IO-free selection logic consumed only by the `WaitlistPromotionService`
mill. Decides which waiting parties get a freed seat, honouring strict FIFO and
the whole-party rule (a party is promoted only when all its still-eligible
members fit at once).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import PromotionStateDTO, WaitingParticipantDTO


def _is_eligible(
    participant: WaitingParticipantDTO,
    *,
    presenter_id: int | None,
    shadowbanned_user_ids: frozenset[int],
) -> bool:
    return (
        participant.user_id != presenter_id
        and not participant.has_conflict
        and participant.user_id not in shadowbanned_user_ids
    )


def _group_into_parties(
    waiting: list[WaitingParticipantDTO],
) -> list[list[WaitingParticipantDTO]]:
    # Party order follows each party's earliest member, which — because
    # `waiting` is already FIFO by creation_time — is the order groups first
    # appear.
    parties: list[list[WaitingParticipantDTO]] = []
    index_by_group: dict[tuple[str, int], int] = {}
    for participant in waiting:
        if (group := participant.promotion_group_key) not in index_by_group:
            index_by_group[group] = len(parties)
            parties.append([])
        parties[index_by_group[group]].append(participant)
    return parties


def _initial_slots_by_owner(waiting: list[WaitingParticipantDTO]) -> dict[int, int]:
    slots_by_owner: dict[int, int] = {}
    for participant in waiting:
        if participant.recipient_user_id not in slots_by_owner:
            slots_by_owner[participant.recipient_user_id] = (
                participant.owner_slots_remaining
            )
    return slots_by_owner


def _membership_slot_action(
    eligible: list[WaitingParticipantDTO], slots_by_owner: dict[int, int]
) -> str:
    slots_needed = Counter(p.recipient_user_id for p in eligible)
    shortfall = [
        owner
        for owner, needed in slots_needed.items()
        if needed > slots_by_owner.get(owner, 0)
    ]
    if not shortfall:
        return "fit"
    if all(slots_by_owner.get(owner, 0) <= 0 for owner in shortfall):
        return "skip"
    return "stop"


def select_promotable_parties(
    state: PromotionStateDTO,
) -> list[list[WaitingParticipantDTO]]:
    # Walks parties front-to-back filling `available_seats`. A party with no
    # still-eligible members (conflict / presenter / shadowban) or no remaining
    # membership slots is skipped — it can never be promoted now, so it does not
    # hold the line. Otherwise the party is promoted only if all its eligible
    # members fit the remaining seats *and* membership allowance at once; the
    # first eligible party that does not fit stops the walk (no leapfrogging).
    seats_remaining = state.available_seats
    selected: list[list[WaitingParticipantDTO]] = []
    if seats_remaining <= 0:
        return selected

    slots_by_owner = _initial_slots_by_owner(state.waiting)

    for party in _group_into_parties(state.waiting):
        eligible = [
            p
            for p in party
            if _is_eligible(
                p,
                presenter_id=state.presenter_id,
                shadowbanned_user_ids=state.shadowbanned_user_ids,
            )
        ]
        if not eligible:
            continue
        match _membership_slot_action(eligible, slots_by_owner):
            case "skip":
                continue
            case "stop":
                break
        if len(eligible) > seats_remaining:
            break
        selected.append(eligible)
        seats_remaining -= len(eligible)
        for owner, count in Counter(p.recipient_user_id for p in eligible).items():
            slots_by_owner[owner] -= count
        if seats_remaining <= 0:
            break

    return selected
