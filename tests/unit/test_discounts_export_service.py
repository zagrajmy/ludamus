from datetime import UTC, datetime
from decimal import Decimal

from ludamus.mills.discounts import DiscountsExportService
from ludamus.pacts.discounts import (
    DiscountDTO,
    DiscountExportColumns,
    DiscountExportLabels,
    DiscountKind,
)
from ludamus.pacts.event import FacilitatorListItemDTO

LABELS = DiscountExportLabels(
    headers=["Rodzaj", "Wartość", "Notatka"],
    kinds={"percent": "Procent", "amount": "Kwota"},
)
NO_COLUMNS = DiscountExportColumns()


def _facilitator(pk, *, display_name="Alice", accreditation_type="guest"):
    return FacilitatorListItemDTO(
        accreditation_type=accreditation_type,
        display_name=display_name,
        pk=pk,
        session_count=0,
        slug=f"facilitator-{pk}",
        user_id=None,
    )


def _discount(facilitator_id, *, value, note):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return DiscountDTO(
        pk=facilitator_id,
        event_id=1,
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=value,
        note=note,
        from_rules=False,
        creation_time=now,
        modification_time=now,
    )


class FakeDiscounts:
    def __init__(self, items=()):
        self._items = list(items)

    def list_by_event(self, _event_pk):
        return list(self._items)


class FakeFacilitators:
    def __init__(self, items=()):
        self._items = list(items)

    def list_by_event(self, _event_id):
        return list(self._items)


class FakeConnections:
    def __init__(self, blob=b"encrypted"):
        self._blob = blob

    def read_secret(self, _sphere_id, _pk):
        return self._blob


class FakeDecryptor:
    def __init__(self):
        self.blobs = []

    def decrypt(self, blob):
        self.blobs.append(blob)
        return b"plaintext"


class FakeWriter:
    def __init__(self):
        self.calls = []

    def write_rows(self, *, secret, spreadsheet_id, rows, tab=""):
        self.calls.append((secret, spreadsheet_id, tab, rows))


def _service(
    *, discounts=None, facilitators=None, connections=None, decryptor=None, writer=None
):
    return DiscountsExportService(
        discounts=discounts or FakeDiscounts(),
        facilitators=facilitators or FakeFacilitators(),
        connections=connections or FakeConnections(),
        decryptor=decryptor or FakeDecryptor(),
        sheet_writer=writer or FakeWriter(),
    )


def _export(service, *, columns=NO_COLUMNS):
    return service.export_to_sheet(
        sphere_id=3,
        event_pk=1,
        connection_id=7,
        spreadsheet_id="sheet-1",
        tab_title="Akredytacje",
        labels=LABELS,
        columns=columns,
    )


class TestDiscountsExportService:
    def test_facilitators_without_accreditation_are_left_out(self):
        facilitators = FakeFacilitators(
            [
                _facilitator(1, display_name="Alice", accreditation_type="guest"),
                _facilitator(2, display_name="Bob", accreditation_type="none"),
            ]
        )
        writer = FakeWriter()
        service = _service(facilitators=facilitators, writer=writer)

        count = _export(service)

        assert count == 1
        assert writer.calls[0][3] == [["Rodzaj", "Wartość", "Notatka"], ["", "", ""]]

    def test_empty_secret_is_not_decrypted(self):
        connections = FakeConnections(blob=b"")
        decryptor = FakeDecryptor()
        writer = FakeWriter()
        service = _service(connections=connections, decryptor=decryptor, writer=writer)

        _export(service)

        assert not decryptor.blobs
        assert writer.calls[0][0] == b""

    def test_facilitator_missing_from_column_cells_keeps_the_row_aligned(self):
        discounts = FakeDiscounts([_discount(1, value=Decimal("15.50"), note="VIP")])
        writer = FakeWriter()
        service = _service(
            discounts=discounts,
            facilitators=FakeFacilitators([_facilitator(1)]),
            writer=writer,
        )
        columns = DiscountExportColumns(headers=["Imię", "Nazwisko"], cells={})

        _export(service, columns=columns)

        assert writer.calls[0][3] == [
            ["Imię", "Nazwisko", "Rodzaj", "Wartość", "Notatka"],
            ["", "", "Procent", "15.50", "VIP"],
        ]
