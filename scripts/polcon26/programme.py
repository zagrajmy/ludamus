from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import cast
from zoneinfo import ZoneInfo

from scripts.polcon26.workbook import (
    SheetData,
    column_index,
    column_name,
    parse_range,
    row_number,
)

SHEETS = ("Piątek", "Sobota", "Niedziela")
SHEET_DATES = {
    "Piątek": date(2026, 9, 25),
    "Sobota": date(2026, 9, 26),
    "Niedziela": date(2026, 9, 27),
}
WARSAW = ZoneInfo("Europe/Warsaw")
BATCH_LIMIT = 250
HEADER_ROW = 3
FIRST_PROGRAMME_COLUMN = 2
MIN_PRESENTER_NAME_LENGTH = 2
MAX_SOURCE_ROW_ID_LENGTH = 64
COLUMN_MINUTES = 15

ROOM_NAME_REPAIRS = (
    ("prelecyjny", "prelekcyjny"),
    ("prelekcyjny (aula 8 w A16)y", "prelekcyjny (aula 8 w A16)"),
    ("komiksowy (aula I w A-20)", "komiksowa (aula I w A-20)"),
)
UNLABELLED_ROOM_GROUPS = {"Sobota": ((31, 33, "Manga i anime sala 106"),)}
TRANSPOSED_TITLE_CELLS = {("Sobota", "G10")}


@dataclass(frozen=True)
class ProgrammeSource:
    source_row_id: str
    sheet: str
    cell: str


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
    items = _with_lane_names(items)
    validate_items(items)
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
    duration = timedelta(minutes=COLUMN_MINUTES * (last_merged_column - column + 1))
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
            room=physical_room,
            leaf_name=physical_room,
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


def lane_counts(items: list[ProgrammeItem]) -> dict[str, int]:
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


def _named_lane(item: ProgrammeItem) -> ProgrammeItem:
    room, leaf_name = lane_names(item.physical_room, item.lane_index)
    return replace(item, venue=replace(item.venue, room=room, leaf_name=leaf_name))


def _with_lane_names(items: list[ProgrammeItem]) -> list[ProgrammeItem]:
    maximum_lanes = lane_counts(items)
    return [
        _named_lane(item) if maximum_lanes[item.physical_room] > 1 else item
        for item in items
    ]


def validate_items(items: list[ProgrammeItem]) -> None:
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
