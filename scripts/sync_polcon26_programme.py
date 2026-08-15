#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import defusedxml.ElementTree
import httpx

SHEETS = ("Piątek", "Sobota", "Niedziela")
SHEET_DATES = {
    "Piątek": date(2026, 9, 25),
    "Sobota": date(2026, 9, 26),
    "Niedziela": date(2026, 9, 27),
}
WARSAW = ZoneInfo("Europe/Warsaw")
XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "doc": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}
VENUE_NAME = "Kampus Uniwersytetu Zielonogórskiego"
BATCH_LIMIT = 250
HEADER_ROW = 3
FIRST_PROGRAMME_COLUMN = 2
MIN_PRESENTER_NAME_LENGTH = 2
MAX_SOURCE_ROW_ID_LENGTH = 64

ROOM_NAME_REPAIRS = (
    ("prelecyjny", "prelekcyjny"),
    ("prelekcyjny (aula 8 w A16)y", "prelekcyjny (aula 8 w A16)"),
    ("komiksowy (aula I w A-20)", "komiksowa (aula I w A-20)"),
)
UNLABELLED_ROOM_GROUPS = {"Sobota": ((31, 33, "Manga i anime sala 106"),)}
TRANSPOSED_TITLE_CELLS = {("Sobota", "G10")}


@dataclass(frozen=True)
class SheetData:
    cells: dict[str, object]
    merges: tuple[str, ...]


@dataclass(frozen=True)
class ProgrammeSource:
    source_row_id: str
    sheet: str
    cell: str


@dataclass
class ProgrammeVenue:
    physical_room: str
    lane_index: int
    room: str
    leaf_name: str
    track: str


@dataclass(frozen=True)
class ProgrammeContent:
    category: str
    title: str
    presenters: list[str]
    description: str


@dataclass(frozen=True)
class ProgrammeTiming:
    start: datetime
    end: datetime


@dataclass
class ProgrammeItem:
    source: ProgrammeSource
    venue: ProgrammeVenue
    content: ProgrammeContent
    timing: ProgrammeTiming

    @property
    def source_row_id(self) -> str:
        return self.source.source_row_id

    @property
    def sheet(self) -> str:
        return self.source.sheet

    @property
    def cell(self) -> str:
        return self.source.cell

    @property
    def physical_room(self) -> str:
        return self.venue.physical_room

    @property
    def lane_index(self) -> int:
        return self.venue.lane_index

    @property
    def room(self) -> str:
        return self.venue.room

    @property
    def leaf_name(self) -> str:
        return self.venue.leaf_name

    @property
    def track(self) -> str:
        return self.venue.track

    @property
    def category(self) -> str:
        return self.content.category

    @property
    def title(self) -> str:
        return self.content.title

    @property
    def presenters(self) -> list[str]:
        return self.content.presenters

    @property
    def description(self) -> str:
        return self.content.description

    @property
    def start(self) -> datetime:
        return self.timing.start

    @property
    def end(self) -> datetime:
        return self.timing.end

    def report_data(self) -> dict[str, object]:
        return {
            "source_row_id": self.source_row_id,
            "sheet": self.sheet,
            "cell": self.cell,
            "physical_room": self.physical_room,
            "lane_index": self.lane_index,
            "room": self.room,
            "leaf_name": self.leaf_name,
            "track": self.track,
            "category": self.category,
            "title": self.title,
            "presenters": self.presenters,
            "description": self.description,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


class McpError(RuntimeError):
    pass


def failure_detail(response_text: str) -> str:
    try:
        payload = cast("dict[str, object]", json.loads(response_text))
    except json.JSONDecodeError:
        return response_text
    results = cast("list[dict[str, object]]", payload.get("results", []))
    if not (failures := [row for row in results if row.get("status") != "ok"]):
        return response_text
    return f"{payload.get('summary')}; failures: {failures}"


class McpClient:
    def __init__(self, *, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.token = token
        self.request_id = 0

    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=60,
            )
            response.raise_for_status()
            body = cast("dict[str, object]", response.json())
        except httpx.HTTPStatusError as error:
            message = (
                f"{name}: HTTP {error.response.status_code}: {error.response.text}"
            )
            raise McpError(message) from error
        except httpx.RequestError as error:
            message = f"{name}: {error}"
            raise McpError(message) from error
        if "error" in body:
            message = f"{name}: {body['error']}"
            raise McpError(message)
        result = cast("dict[str, object]", body.get("result", {}))
        content = cast("list[dict[str, object]]", result.get("content", []))
        response_text = str(content[0].get("text", "")) if content else ""
        if result.get("isError"):
            message = f"{name}: {failure_detail(response_text)}"
            raise McpError(message)
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return response_text


def column_index(reference: str) -> int:
    if (match := re.match(r"[A-Z]+", reference)) is None:
        message = f"Invalid cell reference: {reference}"
        raise ValueError(message)
    result = 0
    for character in match.group():
        result = result * 26 + ord(character) - 64
    return result - 1


def column_name(index: int) -> str:
    result = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def row_number(reference: str) -> int:
    if (match := re.search(r"\d+", reference)) is None:
        message = f"Invalid cell reference: {reference}"
        raise ValueError(message)
    return int(match.group())


def parse_range(reference: str) -> tuple[int, int, int, int]:
    start, separator, end = reference.partition(":")
    if not separator:
        end = start
    return (column_index(start), row_number(start), column_index(end), row_number(end))


def load_workbook(path: Path) -> dict[str, SheetData]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        workbook = defusedxml.ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = defusedxml.ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall("pkg:Relationship", XML_NS)
        }
        result: dict[str, SheetData] = {}
        for sheet in workbook.findall("main:sheets/main:sheet", XML_NS):
            if (name := sheet.attrib["name"]) not in SHEETS:
                continue
            relationship_id = sheet.attrib[f"{{{XML_NS['doc']}}}id"]
            target = targets[relationship_id]
            archive_path = target.removeprefix("/")
            if not archive_path.startswith("xl/"):
                archive_path = f"xl/{archive_path}"
            result[name] = _load_sheet(archive, archive_path, shared_strings)
    if missing := set(SHEETS) - result.keys():
        message = f"Workbook is missing sheets: {', '.join(sorted(missing))}"
        raise ValueError(message)
    return result


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = defusedxml.ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{XML_NS['main']}}}t"))
        for item in root.findall("main:si", XML_NS)
    ]


def _load_sheet(
    archive: zipfile.ZipFile, path: str, shared_strings: list[str]
) -> SheetData:
    root = defusedxml.ElementTree.fromstring(archive.read(path))
    cells: dict[str, object] = {}
    for node in root.findall(".//main:c", XML_NS):
        reference = node.attrib["r"]
        cell_type = node.attrib.get("t")
        value_node = node.find("main:v", XML_NS)
        value: object = value_node.text if value_node is not None else None
        if cell_type == "s" and isinstance(value, str):
            value = shared_strings[int(value)]
        elif cell_type == "inlineStr":
            value = "".join(
                text.text or "" for text in node.iter(f"{{{XML_NS['main']}}}t")
            )
        cells[reference] = value
    merges = tuple(
        node.attrib["ref"] for node in root.findall(".//main:mergeCell", XML_NS)
    )
    return SheetData(cells=cells, merges=merges)


def room_groups(sheet: SheetData) -> list[tuple[int, int, str]]:
    groups: list[tuple[int, int, str]] = []
    for reference in sheet.merges:
        first_column, first_row, last_column, last_row = parse_range(reference)
        room = sheet.cells.get(f"A{first_row}")
        if first_column == last_column == 0 and isinstance(room, str) and room.strip():
            groups.append((first_row, last_row, room))
    covered_rows = {
        row for first, last, _room in groups for row in range(first, last + 1)
    }
    for reference, value in sheet.cells.items():
        row = row_number(reference)
        if (
            column_index(reference) != 0
            or row in covered_rows
            or not isinstance(value, str)
            or not value.strip()
        ):
            continue
        label = sheet.cells.get(f"B{row}")
        if isinstance(label, str) and any(
            expected in label.casefold() for expected in ("tytu", "opis")
        ):
            groups.append((row, row + 2, value))
    return sorted(groups)


def canonical_room(raw: str) -> str:
    value = " ".join(raw.replace("\n", " ").split()).strip(" []")
    for typo, repair in ROOM_NAME_REPAIRS:
        value = value.replace(typo, repair)
    replacements = (
        (
            r"(?i)^rpg\s*-\s*sesje(?:\s+2h|\s+4h)?\s*\[?sala\s+(\d+)\]?$",
            r"RPG — sala \1",
        ),
        (
            r"(?i)^rpg\s*-\s*prelekcyjny\s*\[?sala\s+(\d+)\]?$",
            r"RPG prelekcje — sala \1",
        ),
        (r"(?i)^rpg\s*-\s*prelekcyjny$", "RPG prelekcje — sala 115"),
        (r"(?i)^sala\s+20\s*-\s*warsztat(?:owa|y)$", "Sala 20 — warsztatowa"),
        (r"(?i)^sala\s+12\s*-\s*retro gralnia(?:\s+A16)?$", "Sala 12 — Retro Gralnia"),
        (r"(?i)^manga i anime\s+sala\s+(\d+)$", r"Manga i anime — sala \1"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    aliases = {
        "naukowy": "Naukowy (Biblioteka UZ)",
        "naukowy (Biblioteka UZ)": "Naukowy (Biblioteka UZ)",
        "Games Room (Games room parter A20)": "Games Room",
        "Turniejowa (Games room parter A20)": "Turniejowa Games Room",
        "Turniejowa Games room": "Turniejowa Games Room",
    }
    return aliases.get(value, value[:1].upper() + value[1:])


def track_for(room: str) -> str:
    lowered = room.casefold()
    mappings = (
        ("rpg", "RPG"),
        ("manga", "Manga i anime"),
        ("komiks", "Komiks"),
        ("konkurs", "Konkursy"),
        ("nauk", "Nauka"),
        ("250 lat", "250 lat polskiej fantastyki"),
        ("fandom", "Fandom"),
        ("retro", "Retro Gralnia"),
        ("bitew", "Gry bitewne"),
        ("warsztat", "Warsztaty"),
        ("games room", "Games Room"),
        ("turniej", "Games Room"),
    )
    return next((track for marker, track in mappings if marker in lowered), "Prelekcje")


def category_for(room: str, title: str) -> str:
    combined = f"{room} {title}".casefold()
    if room.casefold().startswith("rpg — sala"):
        return "Sesja RPG"
    if "warsztat" in combined or "stwórz" in title.casefold():
        return "Warsztaty"
    if any(marker in combined for marker in ("konkurs", "quiz", "kalambur")):
        return "Konkurs"
    if any(
        marker in combined
        for marker in ("chill room", "games room", "retro gralnia", "gry bitewne")
    ):
        return "Strefa stała"
    if any(marker in title.casefold() for marker in ("panel", "debata", "forum")):
        return "Panel dyskusyjny"
    return "Prelekcja"


def clean_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split()).strip()
    lowered = title.casefold()
    placeholders = {"opis i tytuł", "tytuł", "tytuł???", "???? tytuł"}
    if not title or lowered in placeholders or lowered.startswith("????"):
        return None
    if lowered.startswith("zaproponowałem na razie"):
        return None
    return title


def clean_description(value: object) -> str:
    if not isinstance(value, str):
        return ""
    description = value.strip()
    lowered = description.casefold().strip(" !.")
    placeholders = {
        "opis",
        "opis i tytuł",
        "potrzebny opis",
        "dodać opis",
        "ustalić opis",
        "potrzebny opis potrzebny prowadzący",
    }
    if (
        lowered in placeholders
        or "potrzebny opis" in lowered
        or lowered.startswith(("dodać opis", "ustalić szczegóły"))
    ):
        return ""
    return description


def presenter_names(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    presenters = " ".join(value.split()).strip()
    lowered = presenters.casefold()
    if (
        not presenters
        or "????" in presenters
        or lowered in {"prowadzący", "kto", "nikt"}
        or lowered.startswith("w zależności od ilości")
    ):
        return []
    presenters = re.sub(
        r"(?i)\b(prowadzenie|uczestnicy|gościmy)\s*:\s*", "", presenters
    )
    presenters = re.sub(r"(?i)\s+-\s+prowadzący\s*:\s*", ", ", presenters)
    presenters = re.sub(r"(?i)^prowadzący\s*:\s*", "", presenters)
    return [
        name.strip(" -")
        for name in re.split(r"\s*(?:,|;|\n|\s+i\s+)\s*", presenters)
        if len(name.strip(" -")) >= MIN_PRESENTER_NAME_LENGTH
    ]


def extract_programme(workbook: dict[str, SheetData]) -> list[ProgrammeItem]:
    items = [
        item
        for sheet_name in SHEETS
        for item in _extract_sheet_programme(
            sheet_name=sheet_name, sheet=workbook[sheet_name]
        )
    ]
    _assign_lanes(items)
    _validate_items(items)
    return items


def _extract_sheet_programme(
    *, sheet_name: str, sheet: SheetData
) -> list[ProgrammeItem]:
    groups = room_groups(sheet)
    groups.extend(UNLABELLED_ROOM_GROUPS.get(sheet_name, ()))
    header_times = _header_times(sheet_name=sheet_name, sheet=sheet)
    first_column, last_column = min(header_times), max(header_times)
    merge_at = _schedule_merges(
        sheet=sheet, first_column=first_column, last_column=last_column
    )
    return [
        item
        for first_row, last_row, raw_room in sorted(groups)
        for item in _extract_room_programme(
            sheet_name=sheet_name,
            sheet=sheet,
            header_times=header_times,
            merge_at=merge_at,
            first_column=first_column,
            last_column=last_column,
            first_row=first_row,
            last_row=last_row,
            raw_room=raw_room,
        )
    ]


def _header_times(*, sheet_name: str, sheet: SheetData) -> dict[int, float]:
    result = {
        column_index(reference): float(value)
        for reference, value in sheet.cells.items()
        if row_number(reference) == HEADER_ROW
        and column_index(reference) >= FIRST_PROGRAMME_COLUMN
        and isinstance(value, str)
        and re.fullmatch(r"\d*\.\d+", value)
    }
    if not result:
        message = f"{sheet_name}: no fractional time headers in row {HEADER_ROW}"
        raise ValueError(message)
    return result


def _schedule_merges(
    *, sheet: SheetData, first_column: int, last_column: int
) -> dict[tuple[int, int], tuple[int, int, str]]:
    result = {}
    for reference in sheet.merges:
        first, row, last, last_row = parse_range(reference)
        if first_column <= first <= last_column and last <= last_column + 1:
            result[row, first] = (last, last_row, reference)
    return result


def _extract_room_programme(
    *,
    sheet_name: str,
    sheet: SheetData,
    header_times: dict[int, float],
    merge_at: dict[tuple[int, int], tuple[int, int, str]],
    first_column: int,
    last_column: int,
    first_row: int,
    last_row: int,
    raw_room: str,
) -> list[ProgrammeItem]:
    physical_room = canonical_room(raw_room)
    title_rows = [
        row
        for row in range(first_row, last_row + 1)
        if isinstance(sheet.cells.get(f"B{row}"), str)
        and "tytu" in cast("str", sheet.cells[f"B{row}"]).casefold()
    ]
    result = []
    for lane_offset, title_row in enumerate(title_rows):
        lane_index = lane_offset + 1
        region_end = (
            title_rows[lane_index] if lane_index < len(title_rows) else last_row + 1
        )
        result.extend(
            _extract_lane_programme(
                sheet_name=sheet_name,
                sheet=sheet,
                header_times=header_times,
                merge_at=merge_at,
                first_column=first_column,
                last_column=last_column,
                physical_room=physical_room,
                title_row=title_row,
                region_end=region_end - 1,
                lane_index=lane_index,
            )
        )
    return result


def _extract_lane_programme(
    *,
    sheet_name: str,
    sheet: SheetData,
    header_times: dict[int, float],
    merge_at: dict[tuple[int, int], tuple[int, int, str]],
    first_column: int,
    last_column: int,
    physical_room: str,
    title_row: int,
    region_end: int,
    lane_index: int,
) -> list[ProgrammeItem]:
    metadata_rows = _metadata_rows(sheet, title_row, region_end)
    result = []
    for column in range(first_column, last_column + 1):
        item = _extract_programme_item(
            sheet_name=sheet_name,
            sheet=sheet,
            header_times=header_times,
            merge_at=merge_at,
            physical_room=physical_room,
            title_row=title_row,
            lane_index=lane_index,
            metadata_rows=metadata_rows,
            column=column,
        )
        if item is not None:
            result.append(item)
    return result


def _extract_programme_item(
    *,
    sheet_name: str,
    sheet: SheetData,
    header_times: dict[int, float],
    merge_at: dict[tuple[int, int], tuple[int, int, str]],
    physical_room: str,
    title_row: int,
    lane_index: int,
    metadata_rows: dict[str, int],
    column: int,
) -> ProgrammeItem | None:
    cell = f"{column_name(column)}{title_row}"
    if (title := clean_title(sheet.cells.get(cell))) is None:
        return None
    if (merge := merge_at.get((title_row, column))) is None:
        message = f"{sheet_name}!{cell}: scheduled title is not merged"
        raise ValueError(message)
    last_merged_column, _last_merged_row, _reference = merge
    presenter = _metadata_value(sheet, metadata_rows.get("presenter"), column)
    if (sheet_name, cell) in TRANSPOSED_TITLE_CELLS:
        if not (isinstance(presenter, str) and presenter.strip()):
            message = f"{sheet_name}!{cell}: expected a transposed title, found none"
            raise ValueError(message)
        title, presenter = presenter.strip(), title
    description = clean_description(
        _metadata_value(sheet, metadata_rows.get("description"), column)
    )
    system = _metadata_value(sheet, metadata_rows.get("system"), column)
    if isinstance(system, str) and system.strip():
        description = f"System: {system.strip()}\n\n{description}".strip()
    minutes = round(header_times[column] * 24 * 60)
    start = datetime.combine(
        SHEET_DATES[sheet_name], time.min, tzinfo=WARSAW
    ) + timedelta(minutes=minutes)
    duration = timedelta(minutes=15 * (last_merged_column - column + 1))
    return ProgrammeItem(
        source=ProgrammeSource(
            source_row_id=(
                f"polcon26-{sheet_name[:3].lower()}-"
                f"{title_row}-{column_name(column).lower()}"
            ),
            sheet=sheet_name,
            cell=cell,
        ),
        venue=ProgrammeVenue(
            physical_room=physical_room,
            lane_index=lane_index,
            room="",
            leaf_name="",
            track=track_for(physical_room),
        ),
        content=ProgrammeContent(
            category=category_for(physical_room, title),
            title=title,
            presenters=presenter_names(presenter),
            description=description,
        ),
        timing=ProgrammeTiming(start=start, end=start + duration),
    )


def _metadata_rows(sheet: SheetData, first_row: int, last_row: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in range(first_row + 1, last_row + 1):
        label = sheet.cells.get(f"B{row}")
        if not isinstance(label, str):
            continue
        lowered = label.casefold()
        if "prowadzą" in lowered:
            result["presenter"] = row
        elif "opis" in lowered:
            result["description"] = row
        elif "system" in lowered:
            result["system"] = row
    return result


def _metadata_value(sheet: SheetData, row: int | None, column: int) -> object:
    return sheet.cells.get(f"{column_name(column)}{row}") if row is not None else None


def _lane_counts(items: list[ProgrammeItem]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.physical_room] = max(counts[item.physical_room], item.lane_index)
    return counts


def lane_names(physical_room: str, lane_index: int) -> tuple[str, str]:
    label = "stół" if physical_room.startswith("RPG —") else "stanowisko"
    return (
        f"{physical_room} — {label} {lane_index}",
        f"{label.capitalize()} {lane_index}",
    )


def _assign_lanes(items: list[ProgrammeItem]) -> None:
    maximum_lanes = _lane_counts(items)
    for item in items:
        if maximum_lanes[item.physical_room] == 1:
            item.venue.room = item.physical_room
            item.venue.leaf_name = item.physical_room
            continue
        item.venue.room, item.venue.leaf_name = lane_names(
            item.physical_room, item.lane_index
        )


def _validate_items(items: list[ProgrammeItem]) -> None:
    source_ids = [item.source_row_id for item in items]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Duplicate source_row_id values")
    if any(len(source_id) > MAX_SOURCE_ROW_ID_LENGTH for source_id in source_ids):
        raise ValueError("A source_row_id exceeds 64 characters")
    by_room: dict[str, list[ProgrammeItem]] = defaultdict(list)
    for item in items:
        if item.end <= item.start:
            message = f"{item.source_row_id}: non-positive duration"
            raise ValueError(message)
        by_room[item.room].append(item)
    for room, room_items in by_room.items():
        ordered = sorted(room_items, key=lambda item: item.start)
        for previous, current in pairwise(ordered):
            if current.start < previous.end:
                message = (
                    f"Overlapping programme in {room}: "
                    f"{previous.source_row_id} and {current.source_row_id}"
                )
                raise ValueError(message)


def iso_duration(duration: timedelta) -> str:
    minutes = int(duration.total_seconds() // 60)
    hours, remaining_minutes = divmod(minutes, 60)
    return (
        "PT"
        + (f"{hours}H" if hours else "")
        + (f"{remaining_minutes}M" if remaining_minutes else "")
    )


def quality_warnings(items: list[ProgrammeItem]) -> list[str]:
    warnings = []
    for item in items:
        if not item.presenters:
            warnings.append(f"{item.source_row_id}: no facilitator — {item.title}")
        if "???" in item.title or "???" in item.description:
            warnings.append(
                f"{item.source_row_id}: placeholder marks need review — {item.title}"
            )
        if not item.description:
            warnings.append(f"{item.source_row_id}: no description — {item.title}")
    return warnings


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
    maximum_lanes = _lane_counts(items)
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
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
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
    space_ids, category_ids, facilitator_ids, track_ids = ensure_supporting_data(
        client=client, event_id=args.event_id, items=items
    )
    session_count, assignment_count = create_and_assign_sessions(
        client=client,
        items=items,
        space_ids=space_ids,
        category_ids=category_ids,
        facilitator_ids=facilitator_ids,
        track_ids=track_ids,
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
