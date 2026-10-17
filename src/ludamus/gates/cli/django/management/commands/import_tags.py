"""Seed the global tag vocabulary from a CSV of category,name,slug,parent rows.

Re-running the same file changes nothing; ``--force`` rewrites the name and
parent of tags already stored. Bad rows are reported and the rest imports.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from django.core.management.base import BaseCommand, CommandError

from ludamus.inits.services import Services

if TYPE_CHECKING:
    from django.core.management.base import CommandParser

    from ludamus.pacts.tags import ImportTagRowDict

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"category", "name"}


class _Options(TypedDict):
    file: Path
    force: bool


def _read_rows(path: Path) -> list[ImportTagRowDict]:
    try:
        reader = csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")))
        header = next(reader, [])
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        msg = f"Cannot read {path}: {exc}"
        raise CommandError(msg) from exc
    if missing := _REQUIRED_COLUMNS - set(header):
        msg = f"{path} lacks the column(s): {', '.join(sorted(missing))}"
        raise CommandError(msg)
    columns = {column: index for index, column in enumerate(header)}

    def cell(row: list[str], column: str) -> str:
        index = columns.get(column, len(row))
        return row[index] if index < len(row) else ""

    try:
        return [
            {
                "line": reader.line_num,
                "category": cell(row, "category"),
                "name": cell(row, "name"),
                "slug": cell(row, "slug"),
                "parent": cell(row, "parent"),
            }
            for row in reader
            if row
        ]
    except csv.Error as exc:
        msg = f"Cannot read {path}: {exc}"
        raise CommandError(msg) from exc


class Command(BaseCommand):
    help = "Import global tags from a CSV file (category,name,slug,parent)."
    force_help = "Update the name and parent of tags whose slug already exists."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("file", type=Path)
        parser.add_argument("--force", action="store_true", help=self.force_help)

    def handle(self, *_args: *tuple[()], **options: Unpack[_Options]) -> None:
        path = options["file"]
        report = Services().tags.import_rows(_read_rows(path), force=options["force"])
        for error in report.errors:
            self.stderr.write(error)
        summary = (
            f"Tags: {report.created} created, {report.skipped} skipped, "
            f"{report.updated} updated, {len(report.errors)} rejected."
        )
        logger.info("%s from %s", summary, path)
        self.stdout.write(self.style.SUCCESS(summary))
