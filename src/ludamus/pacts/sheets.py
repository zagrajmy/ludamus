from typing import Protocol


class SheetExportError(Exception):
    pass


class SheetWriterProtocol(Protocol):
    # A blank `tab` writes the spreadsheet's first tab.
    def write_rows(
        self,
        *,
        secret: bytes,
        spreadsheet_id: str,
        rows: list[list[str]],
        tab: str = "",
    ) -> None: ...
