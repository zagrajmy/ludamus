"""One-off venue restructure for the POLCON 2026 event.

Renames the venue to "Kampus UZ", extracts A-16/A-20 building spaces, and
moves each room under its building with the short name (sala -> s.), matching
what `scripts.polcon26.seed` now produces — so a later sync maps onto the
renamed spaces instead of creating duplicates. Space ids never change, so
session assignments stay put.

Usage:
    python -m scripts.polcon26.restructure_spaces --event-id N \
        --endpoint https://DOMAIN/mcp/organizer/ [--apply]

Requires LUDAMUS_ORGANIZER_MCP_TOKEN and the update_space MCP tool.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field

from scripts.polcon26.mcp_client import McpClient, McpError
from scripts.polcon26.programme import split_building
from scripts.polcon26.seed import VENUE_NAME

OLD_VENUE_NAME = "Kampus Uniwersytetu Zielonogórskiego"


@dataclass
class Plan:
    venue_id: int
    rename_venue: bool
    buildings: dict[str, int | None] = field(default_factory=dict)
    moves: list[dict[str, object]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return int(self.rename_venue) + len(self.moves)

    def describe(self) -> list[str]:
        lines = [f"rename venue -> {VENUE_NAME!r}"] if self.rename_venue else []
        lines.extend(
            f"move {move['old_name']!r} -> "
            f"[{move['building'] or 'top level'}] {move['name']!r}"
            for move in self.moves
        )
        return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument(
        "--endpoint", default="http://polcon26.localhost:8000/mcp/organizer/"
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes")
    return parser.parse_args()


def build_plan(spaces: list[dict[str, object]]) -> Plan:
    by_name = {str(row["name"]): row for row in spaces}
    if (venue := by_name.get(OLD_VENUE_NAME) or by_name.get(VENUE_NAME)) is None:
        message = f"Venue space {OLD_VENUE_NAME!r} not found"
        raise McpError(message)
    plan = Plan(
        venue_id=int(str(venue["pk"])), rename_venue=venue["name"] == OLD_VENUE_NAME
    )
    for row in spaces:
        pk = int(str(row["pk"]))
        if pk == plan.venue_id or row.get("parent_id") != plan.venue_id:
            continue
        name = str(row["name"])
        building, short = split_building(name)
        if building is None and short == name:
            continue
        if building is not None and building not in plan.buildings:
            existing = by_name.get(building)
            plan.buildings[building] = int(str(existing["pk"])) if existing else None
        plan.moves.append(
            {"pk": pk, "old_name": name, "name": short, "building": building}
        )
    return plan


def apply_plan(client: McpClient, plan: Plan) -> None:
    if plan.rename_venue:
        client.call_object("update_space", {"pk": plan.venue_id, "name": VENUE_NAME})
        print(f"renamed venue -> {VENUE_NAME!r}")
    building_ids: dict[str, int] = {}
    for building, existing_pk in plan.buildings.items():
        if existing_pk is None:
            created = client.call_object(
                "create_space", {"name": building, "parent_id": plan.venue_id}
            )
            building_ids[building] = int(str(created["pk"]))
            print(f"created building {building} (pk {created['pk']})")
        else:
            building_ids[building] = existing_pk
    for move in plan.moves:
        arguments: dict[str, object] = {"pk": move["pk"], "name": move["name"]}
        if building := move["building"]:
            arguments["parent_id"] = building_ids[str(building)]
        client.call_object("update_space", arguments)
        print(f"moved {move['old_name']!r} -> {move['name']!r}")


def main() -> int:
    args = parse_args()
    if not (token := os.environ.get("LUDAMUS_ORGANIZER_MCP_TOKEN", "")):
        raise McpError("LUDAMUS_ORGANIZER_MCP_TOKEN is required")
    client = McpClient(endpoint=args.endpoint, token=token)
    current_event = client.call_object("get_current_event", {})
    if int(str(current_event["pk"])) != args.event_id:
        message = f"Token targets event {current_event['pk']}, not {args.event_id}"
        raise McpError(message)
    spaces = client.call_list(
        "list_spaces", {"event_id": args.event_id, "include_internal": True}
    )
    plan = build_plan(spaces)
    for line in plan.describe():
        print(line)
    if plan.count == 0:
        print("Nothing to do.")
        return 0
    if not args.apply:
        print(f"\nDry run: {plan.count} changes. Pass --apply to write.")
        return 0
    apply_plan(client, plan)
    print(f"Done: {plan.count} changes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except McpError as error:
        print(f"ERROR: {error}")
        raise SystemExit(1) from error
