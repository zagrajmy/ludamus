from datetime import UTC, datetime
from decimal import Decimal

from ludamus.mills.discounts import DiscountsExportService
from ludamus.pacts.discounts import DiscountDTO, DiscountExportLabels, DiscountKind
from ludamus.pacts.legacy import FacilitatorListItemDTO

LABELS = DiscountExportLabels(
    headers=["Twórca", "Typ akredytacji", "Rodzaj", "Wartość", "Notatka"],
    accreditation_types={"guest": "Gość", "none": "Brak"},
    kinds={"percent": "Procent", "amount": "Kwota"},
)


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

    def write_rows(self, *, secret, spreadsheet_id, rows):
        self.calls.append((secret, spreadsheet_id, rows))


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


class TestDiscountsExportService:
    def test_writes_header_and_labelled_rows_in_facilitator_order(self):
        facilitator_count = 2
        facilitators = FakeFacilitators(
            [
                _facilitator(1, display_name="Alice", accreditation_type="guest"),
                _facilitator(2, display_name="Bob", accreditation_type="none"),
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

        count = service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=LABELS,
        )

        assert count == facilitator_count
        assert writer.calls == [
            (
                b"plaintext",
                "sheet-1",
                [
                    ["Twórca", "Typ akredytacji", "Rodzaj", "Wartość", "Notatka"],
                    ["Alice", "Gość", "Procent", "15.50", "note-11"],
                    ["Bob", "Brak", "Kwota", "15.50", "note-10"],
                ],
            )
        ]

    def test_facilitator_without_discount_gets_empty_cells(self):
        facilitators = FakeFacilitators([_facilitator(1)])
        writer = FakeWriter()
        service = _service(facilitators=facilitators, writer=writer)

        count = service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=LABELS,
        )

        assert count == 1
        assert writer.calls[0][2][1] == ["Alice", "Gość", "", "", ""]

    def test_unknown_labels_fall_back_to_raw_values(self):
        facilitators = FakeFacilitators(
            [_facilitator(1, accreditation_type="honorary")]
        )
        discounts = FakeDiscounts([_discount(10, facilitator_id=1)])
        writer = FakeWriter()
        service = _service(
            discounts=discounts, facilitators=facilitators, writer=writer
        )
        labels = DiscountExportLabels(
            headers=LABELS.headers, accreditation_types={}, kinds={}
        )

        service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=labels,
        )

        assert writer.calls[0][2][1] == [
            "Alice",
            "honorary",
            "percent",
            "15.50",
            "note-10",
        ]

    def test_reads_and_decrypts_the_connection_secret(self):
        connections = FakeConnections(blob=b"cipher")
        decryptor = FakeDecryptor()
        service = _service(connections=connections, decryptor=decryptor)

        service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=LABELS,
        )

        assert connections.read == [(3, 7)]
        assert decryptor.blobs == [b"cipher"]

    def test_empty_secret_is_not_decrypted(self):
        connections = FakeConnections(blob=b"")
        decryptor = FakeDecryptor()
        writer = FakeWriter()
        service = _service(connections=connections, decryptor=decryptor, writer=writer)

        service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=LABELS,
        )

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

        service.export_to_sheet(
            sphere_id=3,
            event_pk=1,
            connection_id=7,
            spreadsheet_id="sheet-1",
            labels=LABELS,
        )

        assert facilitators.listed_events == [1]
        assert writer.calls[0][2][1] == ["Alice", "Gość", "Procent", "15.50", "note-10"]
