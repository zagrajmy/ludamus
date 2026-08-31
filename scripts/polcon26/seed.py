from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from operator import itemgetter
from typing import cast

from scripts.polcon26.mcp_client import McpClient, McpError
from scripts.polcon26.programme import (
    ProgrammeItem,
    iso_duration,
    lane_counts,
    lane_names,
)


@dataclass(frozen=True)
class ProgrammeRefs:
    spaces: dict[str, int]
    categories: dict[str, int]
    facilitators: dict[str, int]
    tracks: dict[str, int]


VENUE_NAME = "Kampus UZ"
BATCH_LIMIT = 250


def ensure_supporting_data(
    *, client: McpClient, event_id: int, items: list[ProgrammeItem]
) -> ProgrammeRefs:
    current_event = client.call_object("get_current_event", {})
    if int(current_event["pk"]) != event_id:
        message = (
            f"Organizer token targets event {current_event['pk']}, "
            f"not --event-id {event_id}"
        )
        raise McpError(message)
    spaces = client.call_list(
        "list_spaces", {"event_id": event_id, "include_internal": True}
    )
    space_ids = ensure_spaces(client=client, spaces=spaces, items=items)
    category_ids = ensure_named_rows(
        client=client,
        list_tool="list_proposal_categories",
        create_tool="create_proposal_category",
        event_id=event_id,
        names={item.category for item in items},
    )
    ensure_time_slots(client=client, event_id=event_id, items=items)
    facilitator_ids = {}
    for name in sorted(
        {name for item in items for name in item.presenters}, key=str.casefold
    ):
        row = client.call_object("find_or_create_facilitator", {"display_name": name})
        facilitator_ids[name] = int(row["pk"])
    track_ids = ensure_tracks(
        client=client, event_id=event_id, items=items, space_ids=space_ids
    )
    return ProgrammeRefs(
        spaces=space_ids,
        categories=category_ids,
        facilitators=facilitator_ids,
        tracks=track_ids,
    )


def ensure_spaces(
    *, client: McpClient, spaces: list[dict[str, object]], items: list[ProgrammeItem]
) -> dict[str, int]:
    by_path = {str(row["path"]): row for row in spaces}
    if existing_venue := by_path.get(VENUE_NAME):
        venue_id = int(existing_venue["pk"])
    else:
        venue = client.call_object(
            "create_space",
            {"name": VENUE_NAME, "description": "Obiekt główny programu POLCON 2026."},
        )
        venue_id = int(venue["pk"])
        by_path[VENUE_NAME] = {
            "pk": venue_id,
            "name": VENUE_NAME,
            "path": VENUE_NAME,
            "parent_id": None,
        }
    maximum_lanes = lane_counts(items)
    building_of = {item.physical_room: item.building for item in items}
    building_ids: dict[str, int] = {}
    result = {}
    for physical_room in sorted(maximum_lanes):
        parent_id = venue_id
        parent_path = VENUE_NAME
        if building := building_of.get(physical_room):
            if building not in building_ids:
                building_ids[building] = _ensure_leaf_space(
                    client=client,
                    by_path=by_path,
                    path=f"{VENUE_NAME} > {building}",
                    name=building,
                    parent_id=venue_id,
                )
            parent_id = building_ids[building]
            parent_path = f"{VENUE_NAME} > {building}"
        if (lane_count := maximum_lanes[physical_room]) == 1:
            path = f"{parent_path} > {physical_room}"
            result[physical_room] = _ensure_leaf_space(
                client=client,
                by_path=by_path,
                path=path,
                name=physical_room,
                parent_id=parent_id,
            )
            continue
        physical_path = f"{parent_path} > {physical_room}"
        physical_id = _ensure_leaf_space(
            client=client,
            by_path=by_path,
            path=physical_path,
            name=physical_room,
            parent_id=parent_id,
        )
        for lane_index in range(1, lane_count + 1):
            full_name, leaf_name = lane_names(physical_room, lane_index)
            path = f"{physical_path} > {leaf_name}"
            result[full_name] = _ensure_leaf_space(
                client=client,
                by_path=by_path,
                path=path,
                name=leaf_name,
                parent_id=physical_id,
            )
    return result


def _ensure_leaf_space(
    *,
    client: McpClient,
    by_path: dict[str, dict[str, object]],
    path: str,
    name: str,
    parent_id: int,
) -> int:
    if existing := by_path.get(path):
        return int(existing["pk"])
    created = client.call_object("create_space", {"name": name, "parent_id": parent_id})
    created_id = int(created["pk"])
    by_path[path] = {
        "pk": created_id,
        "name": name,
        "path": path,
        "parent_id": parent_id,
    }
    return created_id


def ensure_named_rows(
    *,
    client: McpClient,
    list_tool: str,
    create_tool: str,
    event_id: int,
    names: set[str],
) -> dict[str, int]:
    rows = client.call_list(list_tool, {"event_id": event_id})
    by_name = {str(row["name"]): int(row["pk"]) for row in rows}
    for name in sorted(names):
        if name not in by_name:
            created = client.call_object(create_tool, {"name": name})
            by_name[name] = int(created["pk"])
    return {name: by_name[name] for name in names}


def ensure_time_slots(
    *, client: McpClient, event_id: int, items: list[ProgrammeItem]
) -> None:
    windows: dict[str, list[datetime]] = {}
    for item in items:
        bounds = windows.setdefault(item.sheet, [item.start, item.end])
        bounds[0] = min(bounds[0], item.start)
        bounds[1] = max(bounds[1], item.end)
    expected = tuple(
        (start, end) for start, end in sorted(windows.values(), key=itemgetter(0))
    )
    rows = client.call_list("list_time_slots", {"event_id": event_id})
    existing = {
        (_parse_datetime(str(row["start_time"])), _parse_datetime(str(row["end_time"])))
        for row in rows
    }
    for start, end in expected:
        if (start.astimezone(UTC), end.astimezone(UTC)) not in existing:
            client.call(
                "create_time_slot",
                {"start_time": start.isoformat(), "end_time": end.isoformat()},
            )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def ensure_tracks(
    *,
    client: McpClient,
    event_id: int,
    items: list[ProgrammeItem],
    space_ids: dict[str, int],
) -> dict[str, int]:
    rows = client.call_list("list_tracks", {"event_id": event_id})
    by_name = {str(row["name"]): row for row in rows}
    result = {}
    for name in sorted({item.track for item in items}):
        track_items = [item for item in items if item.track == name]
        expected_space_ids = sorted({space_ids[item.room] for item in track_items})
        if existing := by_name.get(name):
            actual_space_ids = sorted(cast("list[int]", existing["space_ids"]))
            # Extra spaces are the organizer's business; only a missing one
            # would leave part of this import's programme off the track.
            if missing := sorted(set(expected_space_ids) - set(actual_space_ids)):
                message = (
                    f"Track {name!r} has space IDs {actual_space_ids}, missing "
                    f"{missing}. Update it in the organizer panel."
                )
                raise McpError(message)
            result[name] = int(existing["pk"])
            continue
        created = client.call_object(
            "create_track",
            {
                "name": name,
                "is_public": True,
                "space_ids": expected_space_ids,
                "manager_ids": [],
            },
        )
        result[name] = int(created["pk"])
    return result


def create_and_assign_sessions(
    *, client: McpClient, items: list[ProgrammeItem], refs: ProgrammeRefs
) -> tuple[int, int]:
    created_or_existing: dict[str, int] = {}
    drift: list[str] = []
    for batch in _batches(items):
        inputs = [
            {
                "source_row_id": item.source_row_id,
                "title": item.title,
                "category_id": refs.categories[item.category],
                "description": item.description,
                "duration": iso_duration(item.end - item.start),
                "facilitator_ids": [
                    refs.facilitators[name] for name in item.presenters
                ],
                "track_ids": [refs.tracks[item.track]],
            }
            for item in batch
        ]
        response = client.call_object("create_sessions", {"sessions": inputs})
        for item, row in zip(
            batch, cast("list[dict[str, object]]", response["results"]), strict=True
        ):
            session = cast("dict[str, object]", row["session"])
            expected = {
                "title": item.title,
                "description": item.description,
                "duration": iso_duration(item.end - item.start),
                "category_id": refs.categories[item.category],
            }
            differences = [
                field
                for field, value in expected.items()
                if session.get(field) != value
            ]
            if differences:
                drift.append(f"{item.source_row_id}: {', '.join(differences)}")
                continue
            created_or_existing[item.source_row_id] = int(session["pk"])
    if drift:
        details = "\n".join(f"  - {line}" for line in drift)
        message = (
            "Existing sessions differ from the workbook. The create API does not "
            f"overwrite them; reconcile these rows before assigning:\n{details}"
        )
        raise McpError(message)
    assignment_count = 0
    for batch in _batches(items):
        assignments = [
            {
                "session_id": created_or_existing[item.source_row_id],
                "space_id": refs.spaces[item.room],
                "start_time": item.start.isoformat(),
                "end_time": item.end.isoformat(),
            }
            for item in batch
        ]
        client.call("assign_sessions", {"assignments": assignments})
        assignment_count += len(assignments)
    return len(created_or_existing), assignment_count


def _batches(items: list[ProgrammeItem]) -> list[list[ProgrammeItem]]:
    return [
        items[index : index + BATCH_LIMIT]
        for index in range(0, len(items), BATCH_LIMIT)
    ]
