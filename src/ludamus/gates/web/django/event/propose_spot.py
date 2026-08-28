"""The spot step: the free programme cells a walk-up claim can pick from."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.propose import SpotClaim

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.timetable import FreeSpotSpaceDTO

# The session round-trips through JSON, so a stored claim comes back as a list.
_STORED_SPOT_LENGTH = 2


def spot_descriptors(
    spaces: Sequence[FreeSpotSpaceDTO], selected: SpotClaim | None
) -> list[dict[str, object]]:
    """Lay the free cells out for the picker: parent group, room, then slots.

    Returns:
        One entry per parent group in tree order, each carrying its rooms and
        each room the slots nothing occupies it for.
    """
    groups: list[dict[str, object]] = []
    rooms: list[dict[str, object]] = []
    group_name: str | None = None
    for space in spaces:
        if group_name is None or group_name != space.group:
            rooms = []
            group_name = space.group
            groups.append({"name": group_name, "spaces": rooms})
        rooms.append(
            {
                "pk": space.pk,
                "name": space.name,
                "slots": [
                    {
                        "value": spot_value(SpotClaim(space.pk, slot.pk)),
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "is_selected": selected == SpotClaim(space.pk, slot.pk),
                    }
                    for slot in space.slots
                ],
            }
        )
    return groups


def spot_value(claim: SpotClaim) -> str:
    return f"{claim.space_pk}:{claim.time_slot_pk}"


def pick_spot(spaces: Sequence[FreeSpotSpaceDTO], raw: str | None) -> SpotClaim | None:
    """Resolve a submitted "space:slot" pair against the cells still free.

    Returns:
        The claim the picker offered, or None when the pair is malformed or
        names a cell this event does not have free.
    """
    if not raw:
        return None
    space_part, _, slot_part = raw.partition(":")
    try:
        claim = SpotClaim(int(space_part), int(slot_part))
    except ValueError:
        return None
    for space in spaces:
        if space.pk == claim.space_pk and any(
            slot.pk == claim.time_slot_pk for slot in space.slots
        ):
            return claim
    return None


def stored_spot(state: dict[str, object]) -> SpotClaim | None:
    """Read back the pair the wizard parked in the session.

    Returns:
        The stored claim, or None when the step has not been answered.
    """
    stored = state.get("spot")
    if not isinstance(stored, list) or len(stored) != _STORED_SPOT_LENGTH:
        return None
    return SpotClaim(int(stored[0]), int(stored[1]))


def describe_spot(
    spaces: Sequence[FreeSpotSpaceDTO], claim: SpotClaim | None
) -> dict[str, object] | None:
    """Name the cell a claim points at, for the review step.

    Returns:
        The room, its group and the slot's hours, or None when the claim names
        nothing still free.
    """
    if claim is None:
        return None
    for space in spaces:
        if space.pk != claim.space_pk:
            continue
        for slot in space.slots:
            if slot.pk == claim.time_slot_pk:
                return {
                    "space_name": space.name,
                    "group": space.group,
                    "start_time": slot.start_time,
                    "end_time": slot.end_time,
                }
    return None
