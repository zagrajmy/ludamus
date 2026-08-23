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


def _discount(pk, *, event_id=1, facilitator_id=1, kind=DiscountKind.PERCENT):
    return DiscountDTO(
        pk=pk,
        event_id=event_id,
        facilitator_id=facilitator_id,
        kind=kind,
        value=Decimal("15.50"),
        note=f"note-{pk}",
        from_rules=False,
        creation_time=datetime(2026, 6, 19, tzinfo=UTC),
        modification_time=datetime(2026, 6, 19, tzinfo=UTC),
    )


class FakeDiscounts:
    def __init__(self, items=()):
        self._items = list(items)

    def list_by_event(self, event_pk):
        return [d for d in self._items if d.event_id == event_pk]


class FakeFacilitators:
    def __init__(self, items=()):
        self._items = list(items)
        self.listed_events = []

    def list_by_event(self, event_id):
        self.listed_events.append(event_id)
        return list(self._items)


class FakeConnections:
    def __init__(self, blob=b"encrypted"):
        self._blob = blob
        self.read = []

    def read_secret(self, sphere_id, pk):
        self.read.append((sphere_id, pk))
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

    def write_rows(self, *, secret, spreadsheet_id, tab_title, rows):
        self.calls.append((secret, spreadsheet_id, tab_title, rows))


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


def _export(service, *, labels=LABELS, columns=NO_COLUMNS):
    return service.export_to_sheet(
        sphere_id=3,
        event_pk=1,
        connection_id=7,
        spreadsheet_id="sheet-1",
        tab_title="Akredytacje",
        labels=labels,
        columns=columns,
    )


class TestDiscountsExportService:
    def test_writes_header_and_labelled_rows_in_facilitator_order(self):
        facilitator_count = 2
        facilitators = FakeFacilitators(
            [
                _facilitator(1, display_name="Alice", accreditation_type="guest"),
                _facilitator(2, display_name="Bob", accreditation_type="honorary"),
            ]
        )
        discounts = FakeDiscounts(
            [
                _discount(10, facilitator_id=2, kind=DiscountKind.AMOUNT),
                _discount(11, facilitator_id=1, kind=DiscountKind.PERCENT),
            ]
        )
        writer = FakeWriter()
        service = _service(
            discounts=discounts, facilitators=facilitators, writer=writer
        )

        count = _export(service)

        assert count == facilitator_count
        assert writer.calls == [
            (
                b"plaintext",
                "sheet-1",
                "Akredytacje",
                [
                    ["Rodzaj", "Wartość", "Notatka"],
                    ["Procent", "15.50", "note-11"],
                    ["Kwota", "15.50", "note-10"],
                ],
            )
        ]

    def test_chosen_columns_are_written_before_the_discount_ones(self):
        facilitators = FakeFacilitators(
            [_facilitator(1), _facilitator(2, display_name="Bob")]
        )
        discounts = FakeDiscounts([_discount(10, facilitator_id=1)])
        writer = FakeWriter()
        service = _service(
            discounts=discounts, facilitators=facilitators, writer=writer
        )

        _export(
            service,
            columns=DiscountExportColumns(
                headers=["Imię", "Opiekun"],
                cells={1: ["Alicja", "Ola"], 2: ["Bogdan", ""]},
            ),
        )

        assert writer.calls[0][3] == [
            ["Imię", "Opiekun", "Rodzaj", "Wartość", "Notatka"],
            ["Alicja", "Ola", "Procent", "15.50", "note-10"],
            ["Bogdan", "", "", "", ""],
        ]

    def test_facilitator_without_chosen_column_values_keeps_the_discount_cells(self):
        facilitators = FakeFacilitators([_facilitator(1)])
        writer = FakeWriter()
        service = _service(facilitators=facilitators, writer=writer)

        _export(service, columns=DiscountExportColumns(headers=["Imię"], cells={}))

        assert writer.calls[0][3] == [
            ["Imię", "Rodzaj", "Wartość", "Notatka"],
            ["", "", ""],
        ]

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

    def test_unknown_labels_fall_back_to_raw_values(self):
        facilitators = FakeFacilitators(
            [_facilitator(1, accreditation_type="honorary")]
        )
        discounts = FakeDiscounts([_discount(10, facilitator_id=1)])
        writer = FakeWriter()
        service = _service(
            discounts=discounts, facilitators=facilitators, writer=writer
        )

        _export(service, labels=DiscountExportLabels(headers=LABELS.headers, kinds={}))

        assert writer.calls[0][3][1] == ["percent", "15.50", "note-10"]

    def test_reads_and_decrypts_the_connection_secret(self):
        connections = FakeConnections(blob=b"cipher")
        decryptor = FakeDecryptor()
        service = _service(connections=connections, decryptor=decryptor)

        _export(service)

        assert connections.read == [(3, 7)]
        assert decryptor.blobs == [b"cipher"]

    def test_empty_secret_is_not_decrypted(self):
        connections = FakeConnections(blob=b"")
        decryptor = FakeDecryptor()
        writer = FakeWriter()
        service = _service(connections=connections, decryptor=decryptor, writer=writer)

        _export(service)

        assert not decryptor.blobs
        assert writer.calls[0][0] == b""

    def test_scopes_discounts_and_facilitators_to_the_event(self):
        facilitators = FakeFacilitators([_facilitator(1)])
        discounts = FakeDiscounts(
            [
                _discount(10, event_id=1, facilitator_id=1),
                _discount(11, event_id=2, facilitator_id=1, kind=DiscountKind.AMOUNT),
            ]
        )
        writer = FakeWriter()
        service = _service(
            discounts=discounts, facilitators=facilitators, writer=writer
        )

        _export(service)

        assert facilitators.listed_events == [1]
        assert writer.calls[0][3][1] == ["Procent", "15.50", "note-10"]
