from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountRosterEntryDTO,
    DiscountsExportServiceProtocol,
    DiscountsServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.discounts import (
        DiscountData,
        DiscountDTO,
        DiscountExportLabels,
        DiscountRepositoryProtocol,
    )
    from ludamus.pacts.legacy import FacilitatorDTO, FacilitatorRepositoryProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sheets import SheetWriterProtocol


def _roster(
    *,
    discounts: DiscountRepositoryProtocol,
    facilitators: FacilitatorRepositoryProtocol,
    event_pk: int,
) -> list[DiscountRosterEntryDTO]:
    discounts_by_facilitator = {
        discount.facilitator_id: discount
        for discount in discounts.list_by_event(event_pk)
    }
    return [
        DiscountRosterEntryDTO(
            facilitator=facilitator,
            discount=discounts_by_facilitator.get(facilitator.pk),
        )
        for facilitator in facilitators.list_by_event(event_pk)
    ]


class DiscountsService(DiscountsServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        discounts: DiscountRepositoryProtocol,
        facilitators: FacilitatorRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._discounts = discounts
        self._facilitators = facilitators

    def list_roster(self, event_pk: int) -> list[DiscountRosterEntryDTO]:
        return _roster(
            discounts=self._discounts,
            facilitators=self._facilitators,
            event_pk=event_pk,
        )

    def read_scoped(self, *, event_pk: int, pk: int) -> DiscountDTO:
        discount = self._discounts.get(pk)
        if discount.event_id != event_pk:
            raise NotFoundError
        return discount

    def read_scoped_facilitator(
        self, *, event_pk: int, facilitator_id: int
    ) -> FacilitatorDTO:
        facilitator = self._facilitators.read(facilitator_id)
        if facilitator.event_id != event_pk:
            raise NotFoundError
        return facilitator

    def create(self, event_pk: int, data: DiscountData) -> DiscountDTO:
        with self._transaction.atomic():
            return self._discounts.create(event_pk, data)

    def update(self, pk: int, data: DiscountData) -> DiscountDTO:
        with self._transaction.atomic():
            return self._discounts.update(pk, data)

    def soft_delete(self, pk: int) -> None:
        with self._transaction.atomic():
            self._discounts.soft_delete(pk)


class DiscountsExportService(DiscountsExportServiceProtocol):
    def __init__(
        self,
        *,
        discounts: DiscountRepositoryProtocol,
        facilitators: FacilitatorRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        sheet_writer: SheetWriterProtocol,
    ) -> None:
        self._discounts = discounts
        self._facilitators = facilitators
        self._connections = connections
        self._decryptor = decryptor
        self._sheet_writer = sheet_writer

    def export_to_sheet(
        self,
        *,
        sphere_id: int,
        event_pk: int,
        connection_id: int,
        spreadsheet_id: str,
        labels: DiscountExportLabels,
    ) -> int:
        # `read_secret` raises NotFoundError for a connection outside the
        # sphere, so a forged connection id cannot borrow another sphere's
        # credentials.
        blob = self._connections.read_secret(sphere_id, connection_id)
        secret = self._decryptor.decrypt(blob) if blob else b""
        entries = _roster(
            discounts=self._discounts,
            facilitators=self._facilitators,
            event_pk=event_pk,
        )
        rows = [list(labels.headers)]
        for entry in entries:
            facilitator, discount = entry.facilitator, entry.discount
            rows.append(
                [
                    facilitator.display_name,
                    labels.accreditation_types.get(
                        facilitator.accreditation_type, facilitator.accreditation_type
                    ),
                    labels.kinds.get(discount.kind, discount.kind) if discount else "",
                    str(discount.value) if discount else "",
                    discount.note if discount else "",
                ]
            )
        self._sheet_writer.write_rows(
            secret=secret, spreadsheet_id=spreadsheet_id, rows=rows
        )
        return len(entries)
