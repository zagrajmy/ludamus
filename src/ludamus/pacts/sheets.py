from typing import Protocol


class SheetExportError(Exception):
    pass


class SheetWriterProtocol(Protocol):
    def write_rows(
        self, *, secret: bytes, spreadsheet_id: str, rows: list[list[str]]
    ) -> None: ...
