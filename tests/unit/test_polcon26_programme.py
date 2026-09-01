import zipfile
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from scripts.polcon26 import programme as sync
from scripts.polcon26 import workbook as wb
from scripts.polcon26.mcp_client import McpClient, McpError, failure_detail

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("RPG - sesje 4h [sala 108]", "RPG — sala 108"),
        ("RPG - prelekcyjny", "RPG prelekcje — sala 115"),
        ("RPG - prelekcyjny sala 117", "RPG prelekcje — sala 117"),
        ("Sala 20 - warsztaty", "Sala 20 — warsztatowa"),
        ("Sala 12 - Retro gralnia A16", "Sala 12 — Retro Gralnia"),
        ("Manga i anime sala 106", "Manga i anime — sala 106"),
        ("[naukowy]", "Naukowy (Biblioteka UZ)"),
        ("Turniejowa Games room", "Turniejowa Games Room"),
        ("prelecyjny (aula 8 w A16)y", "Prelekcyjny (aula 8 w A16)"),
        ("  sala\n 5  ", "Sala 5"),
    ),
)
def test_canonical_room(raw: str, expected: str) -> None:
    assert sync.canonical_room(raw) == expected


@pytest.mark.parametrize(
    ("room", "expected"),
    (
        ("RPG — sala 108", "RPG"),
        ("Manga i anime — sala 106", "Manga i anime"),
        ("Sala 12 — Retro Gralnia", "Retro Gralnia"),
        ("Turniejowa Games Room", "Games Room"),
        ("Naukowy (Biblioteka UZ)", "Nauka"),
        ("Aula A", "Prelekcje"),
    ),
)
def test_track_for(room: str, expected: str) -> None:
    assert sync.track_for(room) == expected


@pytest.mark.parametrize(
    ("room", "title", "expected"),
    (
        ("RPG — sala 108", "Kryta Forteca", "Sesja RPG"),
        ("RPG prelekcje — sala 115", "Jak prowadzić", "Prelekcja"),
        ("Sala 20 — warsztatowa", "Kuźnia", "Warsztaty"),
        ("Aula A", "Stwórz własną mapę", "Warsztaty"),
        ("Aula A", "Wielki quiz fantastyki", "Konkurs"),
        ("Games Room", "Gry planszowe", "Strefa stała"),
        ("Aula A", "Panel o wydawnictwach", "Panel dyskusyjny"),
        ("Aula A", "Historia fandomu", "Prelekcja"),
    ),
)
def test_category_for(room: str, title: str, expected: str) -> None:
    assert sync.category_for(room, title) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("  Wielka   prelekcja ", "Wielka prelekcja"),
        ("Tytuł", None),
        ("???? tytuł", None),
        ("Zaproponowałem na razie coś", None),
        ("Przerwa Techniczna", None),
        ("Warsztaty: ", "Warsztaty"),
        ("", None),
        (None, None),
        (42, None),
    ),
)
def test_clean_title(value: object, expected: str | None) -> None:
    assert sync.clean_title(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("  Prawdziwy opis  ", "Prawdziwy opis"),
        ("Potrzebny opis!", ""),
        ("Dodać opis do tego", ""),
        ("opis", ""),
        (None, ""),
    ),
)
def test_clean_description(value: object, expected: str) -> None:
    assert sync.clean_description(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("Prowadzący: Anna Kowalska", ["Anna Kowalska"]),
        ("Anna Kowalska, Jan Nowak", ["Anna Kowalska", "Jan Nowak"]),
        ("Anna Kowalska i Jan Nowak", ["Anna Kowalska", "Jan Nowak"]),
        ("Prowadzenie: Anna; Jan", ["Anna", "Jan"]),
        (
            "Rozmawiają Anna, Jan\nProwadzi: Dominika Węcławek",
            ["Anna", "Jan", "Dominika Węcławek"],
        ),
        ("Udział bierze: Xavier Dollo", ["Xavier Dollo"]),
        ("Udział bierą: Stanisław Mąderek", ["Stanisław Mąderek"]),
        ("Michał J. Sobociński:", ["Michał J. Sobociński"]),
        ("Fundacja Dawne Komputery i Gry", ["Fundacja Dawne Komputery i Gry"]),
        ("Sekcja Trzymaj Pion w składzie: Ola, Arek", ["Sekcja Trzymaj Pion"]),
        ("Każdy, kto został na miejscu", []),
        ("????", []),
        ("nikt", []),
        ("W zależności od ilości chętnych", []),
        (None, []),
    ),
)
def test_presenter_names(value: object, expected: list[str]) -> None:
    assert sync.presenter_names(value) == expected


@pytest.mark.parametrize(
    ("physical_room", "lane_index", "expected"),
    (
        ("RPG — sala 108", 2, ("RPG — sala 108 — stół 2", "Stół 2")),
        ("Games Room", 3, ("Games Room — stanowisko 3", "Stanowisko 3")),
    ),
)
def test_lane_names(
    physical_room: str, lane_index: int, expected: tuple[str, str]
) -> None:
    assert sync.lane_names(physical_room, lane_index) == expected


@pytest.mark.parametrize(
    ("reference", "expected"), (("A1", 0), ("B3", 1), ("Z9", 25), ("AA1", 26))
)
def test_column_index(reference: str, expected: int) -> None:
    assert wb.column_index(reference) == expected


@pytest.mark.parametrize("index", (0, 1, 25, 26, 51, 701))
def test_column_name_roundtrips(index: int) -> None:
    assert wb.column_index(f"{wb.column_name(index)}1") == index


@pytest.mark.parametrize(
    ("duration", "expected"),
    (
        (timedelta(minutes=45), "PT45M"),
        (timedelta(hours=1), "PT1H"),
        (timedelta(hours=1, minutes=30), "PT1H30M"),
    ),
)
def test_iso_duration(duration: timedelta, expected: str) -> None:
    assert sync.iso_duration(duration) == expected


def test_failure_detail_summarizes_batch_failures() -> None:
    response_text = (
        '{"summary": {"total": 2, "succeeded": 1, "failed": 1}, "results": '
        '[{"index": 0, "status": "ok"}, {"index": 1, "status": "failed", '
        '"error": "Resource not found"}]}'
    )

    detail = failure_detail(response_text)

    assert "failed" in detail
    assert "Resource not found" in detail


def test_failure_detail_passes_through_plain_text() -> None:
    assert failure_detail("boom") == "boom"


@pytest.mark.parametrize(
    "response_text", ("123", "null", '"just a string"', "[1, 2]", '{"results": 7}')
)
def test_failure_detail_passes_through_non_report_json(response_text: str) -> None:
    assert failure_detail(response_text) == response_text


@pytest.mark.parametrize(
    "endpoint",
    ("http://localhost:8000/mcp/organizer/", "https://zagrajmy.pl/mcp/organizer/"),
)
def test_client_accepts_loopback_http_and_any_https(endpoint: str) -> None:
    assert McpClient(endpoint=endpoint, token="t").endpoint == endpoint


@pytest.mark.parametrize(
    "endpoint", ("http://zagrajmy.pl/mcp/organizer/", "ftp://example.invalid/")
)
def test_client_refuses_to_send_the_token_in_the_clear(endpoint: str) -> None:
    with pytest.raises(McpError):
        McpClient(endpoint=endpoint, token="t")


def _sheet_with_one_room():
    # Row 3 carries fractional day times; row 4 labels the lane, rows 5-6 its
    # metadata. C4:D4 merged means a two-column (30 minute) session.
    cells = {
        "A4": "Sala 5",
        "B4": "Tytuł",
        "B5": "Prowadzący",
        "B6": "Opis",
        "C3": "0.5",
        "D3": "0.510416666666667",
        "E3": "0.520833333333333",
        "C4": "Wprowadzenie",
        "C5": "Anna Kowalska i Jan Nowak",
        "C6": "Opis warsztatu",
        "E4": "Zakończenie",
        "E5": "Prowadzący",
        "E6": "Potrzebny opis",
    }
    return wb.SheetData(cells=cells, merges=("A4:A6", "C4:D4", "E4:E4"))


def _extract_saturday():
    return sync.extract_programme(
        {
            "Piątek": wb.SheetData(cells={"C3": "0.5"}, merges=()),
            "Sobota": _sheet_with_one_room(),
            "Niedziela": wb.SheetData(cells={"C3": "0.5"}, merges=()),
        }
    )


def test_extract_programme_reads_titles_presenters_and_durations() -> None:
    items = sync.extract_programme(
        {name: _sheet_with_one_room() for name in ("Piątek", "Sobota", "Niedziela")}
    )

    saturday = [item for item in items if item.sheet == "Sobota"]
    assert [item.title for item in saturday] == ["Wprowadzenie", "Zakończenie"]
    first = saturday[0]
    assert first.presenters == ["Anna Kowalska", "Jan Nowak"]
    assert first.description == "Opis warsztatu"
    assert first.end - first.start == timedelta(minutes=30)
    assert not saturday[1].description


def test_extract_programme_ignores_hidden_columns_between_visible_columns() -> None:
    visible = _sheet_with_one_room()
    cells = dict(visible.cells)
    cells |= {"F3": "0.53125", "F4": "Po przerwie"}
    hidden = wb.SheetData(
        cells=cells,
        merges=(*visible.merges, "F4:F4"),
        hidden_columns=frozenset({wb.column_index("E1")}),
    )

    items = sync.extract_programme(
        {"Piątek": visible, "Sobota": hidden, "Niedziela": visible}
    )

    saturday = [item for item in items if item.sheet == "Sobota"]
    assert [item.title for item in saturday] == ["Wprowadzenie", "Po przerwie"]


def test_extract_programme_does_not_extrapolate_past_the_time_header() -> None:
    regular = _sheet_with_one_room()
    cells = dict(regular.cells)
    del cells["E3"]
    misaligned = replace(regular, cells=cells)

    items = sync.extract_programme(
        {"Piątek": regular, "Sobota": misaligned, "Niedziela": regular}
    )

    saturday = [item for item in items if item.sheet == "Sobota"]
    assert [item.title for item in saturday] == ["Wprowadzenie"]


def test_extract_programme_rejects_merge_past_the_visible_time_header() -> None:
    regular = _sheet_with_one_room()
    crossing = replace(
        regular,
        merges=tuple(
            "E4:F4" if merge == "E4:E4" else merge for merge in regular.merges
        ),
    )

    with pytest.raises(ValueError, match="scheduled title is not merged"):
        sync.extract_programme(
            {"Piątek": regular, "Sobota": crossing, "Niedziela": regular}
        )


def test_extract_programme_dates_each_sheet_from_its_own_day() -> None:
    items = sync.extract_programme(
        {name: _sheet_with_one_room() for name in ("Piątek", "Sobota", "Niedziela")}
    )

    days = {item.sheet: item.start.date() for item in items}
    assert days == {
        "Piątek": sync.SHEET_DATES["Piątek"],
        "Sobota": sync.SHEET_DATES["Sobota"],
        "Niedziela": sync.SHEET_DATES["Niedziela"],
    }


def test_extract_programme_gives_each_row_a_unique_source_row_id() -> None:
    items = _extract_saturday()

    source_ids = [item.source_row_id for item in items]
    assert len(source_ids) == len(set(source_ids))
    assert all(
        len(source_id) <= sync.MAX_SOURCE_ROW_ID_LENGTH for source_id in source_ids
    )


def test_single_lane_room_keeps_its_plain_name() -> None:
    items = _extract_saturday()

    assert {item.room for item in items} == {"Sala 5"}
    assert {item.leaf_name for item in items} == {"Sala 5"}


def test_shared_room_splits_into_numbered_lanes() -> None:
    cells = dict(_sheet_with_one_room().cells)
    cells |= {"B7": "Tytuł", "B8": "Prowadzący", "C7": "Druga sesja"}
    sheet = wb.SheetData(cells=cells, merges=("A4:A8", "C4:D4", "E4:E4", "C7:C7"))

    items = sync.extract_programme(
        {"Piątek": sheet, "Sobota": sheet, "Niedziela": sheet}
    )

    rooms = {item.room for item in items}
    assert rooms == {"Sala 5 — stanowisko 1", "Sala 5 — stanowisko 2"}
    assert {item.leaf_name for item in items} == {"Stanowisko 1", "Stanowisko 2"}


def test_validate_items_rejects_overlapping_programme_in_one_room() -> None:
    items = _extract_saturday()
    overlapping = replace(
        items[1], timing=sync.ProgrammeTiming(start=items[0].start, end=items[0].end)
    )

    with pytest.raises(ValueError, match="Overlapping programme"):
        sync.validate_items([items[0], overlapping])


def test_validate_items_rejects_duplicate_source_row_ids() -> None:
    items = _extract_saturday()

    with pytest.raises(ValueError, match="Duplicate source_row_id"):
        sync.validate_items([items[0], items[0]])


def test_continuation_marker_borrows_the_sibling_day_content() -> None:
    friday = _sheet_with_one_room()
    saturday_cells = dict(friday.cells)
    saturday_cells["C4"] = "> > > >"
    del saturday_cells["C5"], saturday_cells["C6"]
    saturday = wb.SheetData(cells=saturday_cells, merges=friday.merges)

    items = sync.extract_programme(
        {
            "Piątek": friday,
            "Sobota": saturday,
            "Niedziela": wb.SheetData(cells={"C3": "0.5"}, merges=()),
        }
    )

    borrowed = next(
        item for item in items if item.sheet == "Sobota" and item.cell == "C4"
    )
    assert borrowed.title == "Wprowadzenie"
    assert borrowed.description == "Opis warsztatu"
    assert borrowed.presenters == ["Anna Kowalska", "Jan Nowak"]


def test_arrow_padded_title_keeps_its_core_text() -> None:
    friday = _sheet_with_one_room()
    cells = dict(friday.cells)
    cells["C4"] = "> > Wystawa prac < <"
    saturday = wb.SheetData(cells=cells, merges=friday.merges)

    items = sync.extract_programme(
        {
            "Piątek": wb.SheetData(cells={"C3": "0.5"}, merges=()),
            "Sobota": saturday,
            "Niedziela": wb.SheetData(cells={"C3": "0.5"}, merges=()),
        }
    )

    unpadded = next(item for item in items if item.cell == "C4")
    assert unpadded.title == "Wystawa prac"
    assert unpadded.category == "Strefa stała"


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SHEET_XML = (
    f'<worksheet xmlns="{_MAIN_NS}">'
    '<cols><col min="5" max="6" hidden="1"/></cols><sheetData>'
    '<row r="3"><c r="C3"><v>0.5</v></c></row>'
    '<row r="4"><c r="C4" t="s"><v>0</v></c></row>'
    "</sheetData>"
    '<mergeCells><mergeCell ref="C4:D4"/></mergeCells></worksheet>'
).encode()


def _write_workbook(path: Path, names: tuple[str, ...]) -> None:
    sheets = "".join(
        f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    relationships = "".join(
        f'<Relationship Id="rId{index}" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(names) + 1)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_DOC_NS}">'
            f"<sheets>{sheets}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{_PKG_NS}">{relationships}</Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{_MAIN_NS}"><si><t>Wprowadzenie</t></si></sst>',
        )
        for index in range(1, len(names) + 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _SHEET_XML)


def test_load_workbook_reads_cells_merges_and_shared_strings(tmp_path: Path) -> None:
    path = tmp_path / "programme.xlsx"
    _write_workbook(path, wb.SHEETS)

    sheets = wb.load_workbook(path)

    assert sorted(sheets) == sorted(wb.SHEETS)
    assert sheets["Sobota"].cells == {"C3": "0.5", "C4": "Wprowadzenie"}
    assert sheets["Sobota"].merges == ("C4:D4",)
    assert sheets["Sobota"].hidden_columns == frozenset({4, 5})


def test_load_workbook_rejects_a_workbook_missing_a_day(tmp_path: Path) -> None:
    path = tmp_path / "programme.xlsx"
    _write_workbook(path, ("Piątek",))

    with pytest.raises(ValueError, match="missing sheets: Niedziela, Sobota"):
        wb.load_workbook(path)
