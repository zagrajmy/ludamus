from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

import defusedxml.ElementTree

if TYPE_CHECKING:
    from pathlib import Path

SHEETS = ("Piątek", "Sobota", "Niedziela")
XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "doc": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class SheetData:
    cells: dict[str, object]
    merges: tuple[str, ...]


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
            result[name] = _load_sheet(
                archive=archive, path=archive_path, shared_strings=shared_strings
            )
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
    *, archive: zipfile.ZipFile, path: str, shared_strings: list[str]
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
