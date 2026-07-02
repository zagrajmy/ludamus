"""Business invariants for waiting-list promotion.

Pure, IO-free selection logic consumed only by the `WaitlistPromotionService`
mill. Decides which waiting parties get a freed seat, honouring strict FIFO and
the whole-party rule (a party is promoted only when all its still-eligible
members fit at once).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import PromotionStateDTO, WaitingParticipantDTO


def _is_eligible(
    participant: WaitingParticipantDTO, *, presenter_id: int | None
) -> bool:
    return participant.user_id != presenter_id and not participant.has_conflict


def _group_into_parties(
    waiting: list[WaitingParticipantDTO],
) -> list[list[WaitingParticipantDTO]]:
    # Party order follows each party's earliest member, which — because
    # `waiting` is already FIFO by creation_time — is the order slot owners
    # first appear.
    parties: list[list[WaitingParticipantDTO]] = []
    index_by_owner: dict[int, int] = {}
    for participant in waiting:
        if (owner := participant.effective_slot_owner) not in index_by_owner:
            index_by_owner[owner] = len(parties)
            parties.append([])
        parties[index_by_owner[owner]].append(participant)
    return parties


def select_promotable_parties(
    state: PromotionStateDTO,
) -> list[list[WaitingParticipantDTO]]:
    # Walks parties front-to-back filling `available_seats`. A party with no
    # still-eligible members (conflict / presenter) or no remaining
    # membership slots is skipped — it can never be promoted now, so it does not
    # hold the line. Otherwise the party is promoted only if all its eligible
    # members fit the remaining seats *and* membership allowance at once; the
    # first eligible party that does not fit stops the walk (no leapfrogging).
    seats_remaining = state.available_seats
    selected: list[list[WaitingParticipantDTO]] = []
    if seats_remaining <= 0:
        return selected

    for party in _group_into_parties(state.waiting):
        eligible = [
            p for p in party if _is_eligible(p, presenter_id=state.presenter_id)
        ]
        if not eligible:
            continue
        if (slots_remaining := min(p.owner_slots_remaining for p in eligible)) <= 0:
            continue
        if len(eligible) > seats_remaining or len(eligible) > slots_remaining:
            break
        selected.append(eligible)
        seats_remaining -= len(eligible)
        if seats_remaining <= 0:
            break

    return selected
