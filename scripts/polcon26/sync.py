from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

from scripts.polcon26.mcp_client import McpClient, McpError
from scripts.polcon26.programme import extract_programme, quality_warnings
from scripts.polcon26.seed import create_and_assign_sessions, ensure_supporting_data
from scripts.polcon26.workbook import load_workbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse and safely seed the POLCON 2026 programme workbook."
    )
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--report", type=Path, help="Write normalized rows as JSON")
    parser.add_argument(
        "--apply", action="store_true", help="Write through organizer MCP"
    )
    parser.add_argument("--event-id", type=int, help="Target event primary key")
    parser.add_argument(
        "--endpoint",
        default="http://polcon26.localhost:8000/mcp/organizer/",
        help="Organizer MCP endpoint",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    items = extract_programme(load_workbook(args.workbook))
    warnings = quality_warnings(items)
    report = {
        "workbook": str(args.workbook),
        "summary": {
            "sessions": len(items),
            "rooms": len({item.room for item in items}),
            "facilitators": len({name for item in items for name in item.presenters}),
            "warnings": len(warnings),
        },
        "warnings": warnings,
        "sessions": [item.report_data() for item in items],
    }
    if args.report:
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    displayed_warnings = warnings[:25]
    for warning in displayed_warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if len(warnings) > len(displayed_warnings):
        print(
            f"WARNING: {len(warnings) - len(displayed_warnings)} more; "
            "use --report to inspect all warnings.",
            file=sys.stderr,
        )
    if not args.apply:
        print("Dry run only. Pass --apply to write through organizer MCP.")
        return 0
    if args.event_id is None:
        raise McpError("--event-id is required with --apply")
    if not (token := os.environ.get("LUDAMUS_ORGANIZER_MCP_TOKEN", "")):
        raise McpError("LUDAMUS_ORGANIZER_MCP_TOKEN is required with --apply")
    client = McpClient(endpoint=args.endpoint, token=token)
    refs = ensure_supporting_data(client=client, event_id=args.event_id, items=items)
    session_count, assignment_count = create_and_assign_sessions(
        client=client, items=items, refs=refs
    )
    print(
        f"Applied {session_count} sessions and {assignment_count} assignments. "
        "A repeated run is safe for unchanged source rows."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (McpError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
