from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from scripts.polcon26.mcp_client import McpClient, McpError
from scripts.polcon26.programme import (
    WARSAW,
    ProgrammeItem,
    iso_duration,
    lane_counts,
    lane_names,
)

VENUE_NAME = "Kampus Uniwersytetu Zielonogórskiego"
BATCH_LIMIT = 250


def ensure_supporting_data(
    *, client: McpClient, event_id: int, items: list[ProgrammeItem]
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    current_event = cast("dict[str, object]", client.call("get_current_event", {}))
    if int(current_event["pk"]) != event_id:
        message = (
            f"Organizer token targets event {current_event['pk']}, "
            f"not --event-id {event_id}"
        )
        raise McpError(message)
    spaces = cast(
        "list[dict[str, object]]",
        client.call("list_spaces", {"event_id": event_id, "include_internal": True}),
    )
    space_ids = ensure_spaces(client=client, spaces=spaces, items=items)
    category_ids = ensure_named_rows(
        client=client,
        list_tool="list_proposal_categories",
        create_tool="create_proposal_category",
        event_id=event_id,
        names={item.category for item in items},
    )
    ensure_time_slots(client=client, event_id=event_id)
    facilitator_ids = {}
    for name in sorted(
        {name for item in items for name in item.presenters}, key=str.casefold
    ):
        row = cast(
            "dict[str, object]",
            client.call("find_or_create_facilitator", {"display_name": name}),
        )
        facilitator_ids[name] = int(row["pk"])
    track_ids = ensure_tracks(
        client=client, event_id=event_id, items=items, space_ids=space_ids
    )
    return space_ids, category_ids, facilitator_ids, track_ids


def ensure_spaces(
    *, client: McpClient, spaces: list[dict[str, object]], items: list[ProgrammeItem]
) -> dict[str, int]:
    by_path = {str(row["path"]): row for row in spaces}
    if existing_venue := by_path.get(VENUE_NAME):
        venue_id = int(existing_venue["pk"])
    else:
        venue = cast(
            "dict[str, object]",
            client.call(
                "create_space",
                {
                    "name": VENUE_NAME,
                    "description": "Obiekt główny programu POLCON 2026.",
                },
            ),
        )
        venue_id = int(venue["pk"])
        by_path[VENUE_NAME] = {
            "pk": venue_id,
            "name": VENUE_NAME,
            "path": VENUE_NAME,
            "parent_id": None,
        }
    maximum_lanes = lane_counts(items)
    result = {}
    for physical_room in sorted(maximum_lanes):
        if (lane_count := maximum_lanes[physical_room]) == 1:
            path = f"{VENUE_NAME} > {physical_room}"
            result[physical_room] = _ensure_leaf_space(
                client=client,
                by_path=by_path,
                path=path,
                name=physical_room,
                parent_id=venue_id,
            )
            continue
        physical_path = f"{VENUE_NAME} > {physical_room}"
        if existing_physical := by_path.get(physical_path):
            physical_id = int(existing_physical["pk"])
        else:
            physical = cast(
                "dict[str, object]",
                client.call(
                    "create_space", {"name": physical_room, "parent_id": venue_id}
                ),
            )
            physical_id = int(physical["pk"])
            by_path[physical_path] = {
                "pk": physical_id,
                "name": physical_room,
                "path": physical_path,
                "parent_id": venue_id,
            }
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
    created = cast(
        "dict[str, object]",
        client.call("create_space", {"name": name, "parent_id": parent_id}),
    )
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
    rows = cast(
        "list[dict[str, object]]", client.call(list_tool, {"event_id": event_id})
    )
    by_name = {str(row["name"]): int(row["pk"]) for row in rows}
    for name in sorted(names):
        if name not in by_name:
            created = cast(
                "dict[str, object]", client.call(create_tool, {"name": name})
            )
            by_name[name] = int(created["pk"])
    return {name: by_name[name] for name in names}


def ensure_time_slots(*, client: McpClient, event_id: int) -> None:
    expected = (
        (
            datetime(2026, 9, 25, 16, tzinfo=WARSAW),
            datetime(2026, 9, 25, 20, tzinfo=WARSAW),
        ),
        (
            datetime(2026, 9, 26, 10, tzinfo=WARSAW),
            datetime(2026, 9, 26, 21, tzinfo=WARSAW),
        ),
        (
            datetime(2026, 9, 27, 10, tzinfo=WARSAW),
            datetime(2026, 9, 27, 16, tzinfo=WARSAW),
        ),
    )
    rows = cast(
        "list[dict[str, object]]",
        client.call("list_time_slots", {"event_id": event_id}),
    )
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
    rows = cast(
        "list[dict[str, object]]", client.call("list_tracks", {"event_id": event_id})
    )
    by_name = {str(row["name"]): row for row in rows}
    result = {}
    for name in sorted({item.track for item in items}):
        track_items = [item for item in items if item.track == name]
        expected_space_ids = sorted({space_ids[item.room] for item in track_items})
        if existing := by_name.get(name):
            actual_space_ids = sorted(cast("list[int]", existing["space_ids"]))
            if actual_space_ids != expected_space_ids:
                message = (
                    f"Track {name!r} has space IDs {actual_space_ids}, expected "
                    f"{expected_space_ids}. Update it in the organizer panel."
                )
                raise McpError(message)
            result[name] = int(existing["pk"])
            continue
        created = cast(
            "dict[str, object]",
            client.call(
                "create_track",
                {
                    "name": name,
                    "is_public": True,
                    "space_ids": expected_space_ids,
                    "manager_ids": [],
                },
            ),
        )
        result[name] = int(created["pk"])
    return result


def create_and_assign_sessions(
    *,
    client: McpClient,
    items: list[ProgrammeItem],
    space_ids: dict[str, int],
    category_ids: dict[str, int],
    facilitator_ids: dict[str, int],
    track_ids: dict[str, int],
) -> tuple[int, int]:
    created_or_existing: dict[str, int] = {}
    drift: list[str] = []
    for batch in _batches(items):
        inputs = [
            {
                "source_row_id": item.source_row_id,
                "title": item.title,
                "category_id": category_ids[item.category],
                "description": item.description,
                "duration": iso_duration(item.end - item.start),
                "facilitator_ids": [facilitator_ids[name] for name in item.presenters],
                "track_ids": [track_ids[item.track]],
            }
            for item in batch
        ]
        response = cast(
            "dict[str, object]", client.call("create_sessions", {"sessions": inputs})
        )
        for item, row in zip(
            batch, cast("list[dict[str, object]]", response["results"]), strict=True
        ):
            session = cast("dict[str, object]", row["session"])
            expected = {
                "title": item.title,
                "description": item.description,
                "duration": iso_duration(item.end - item.start),
                "category_id": category_ids[item.category],
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
                "space_id": space_ids[item.room],
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
