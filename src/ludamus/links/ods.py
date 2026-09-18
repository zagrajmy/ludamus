"""Write a table of strings as an OpenDocument spreadsheet."""

from __future__ import annotations

import re
from io import BytesIO
from typing import TYPE_CHECKING

from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import LineBreak, P

if TYPE_CHECKING:
    from collections.abc import Sequence

# LibreOffice refuses these in a sheet name, and an empty name altogether.
_FORBIDDEN_IN_SHEET_NAME = re.compile(r"[\[\]*?:/\\]")
_FALLBACK_SHEET_NAME = "Sheet1"


def _sheet_name(title: str) -> str:
    return _FORBIDDEN_IN_SHEET_NAME.sub("", title).strip() or _FALLBACK_SHEET_NAME


def spreadsheet_bytes(*, rows: Sequence[Sequence[str]], sheet_title: str) -> bytes:
    # Every cell is a string cell with no formula attribute, so a value that
    # starts with "=" reads back as the text it is. A raw newline inside the
    # paragraph is whitespace to a reader; the line-break element survives.
    document = OpenDocumentSpreadsheet()
    table = Table(name=_sheet_name(sheet_title))
    for row in rows:
        table_row = TableRow()
        for value in row:
            paragraph = P()
            for index, line in enumerate(value.split("\n")):
                if index:
                    paragraph.addElement(LineBreak())
                paragraph.addText(line)
            cell = TableCell(valuetype="string")
            cell.addElement(paragraph)
            table_row.addElement(cell)
        table.addElement(table_row)
    document.spreadsheet.addElement(table)
    buffer = BytesIO()
    document.write(buffer)
    return buffer.getvalue()
