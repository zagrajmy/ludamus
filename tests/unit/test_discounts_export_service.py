from ludamus.mills.discounts import DiscountsExportService
from ludamus.pacts.discounts import DiscountExportColumns, DiscountExportLabels
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


class FakeDiscounts:
    @staticmethod
    def list_by_event(event_pk):
        _ = event_pk
        return []


class FakeFacilitators:
    def __init__(self, items=()):
        self._items = list(items)

    def list_by_event(self, event_id):
        _ = event_id
        return list(self._items)


class FakeConnections:
    def __init__(self, blob=b"encrypted"):
        self._blob = blob

    def read_secret(self, sphere_id, pk):
        _ = (sphere_id, pk)
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


def _service(*, facilitators=None, connections=None, decryptor=None, writer=None):
    return DiscountsExportService(
        discounts=FakeDiscounts(),
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
