from typing import TYPE_CHECKING

from ludamus.pacts.discounts import DiscountsExportServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts.discounts import (
        DiscountData,
        DiscountDTO,
        DiscountExportLabels,
        DiscountRepositoryProtocol,
        SheetWriterProtocol,
    )
    from ludamus.pacts.legacy import FacilitatorRepositoryProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class DiscountsService:
    def __init__(
        self, transaction: TransactionProtocol, discounts: DiscountRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._discounts = discounts

    def list_by_event(self, event_pk: int) -> list[DiscountDTO]:
        return self._discounts.list_by_event(event_pk)

    def get(self, pk: int) -> DiscountDTO:
        return self._discounts.get(pk)

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
        facilitators = self._facilitators.list_by_event(event_pk)
        discounts = {
            discount.facilitator_id: discount
            for discount in self._discounts.list_by_event(event_pk)
        }
        rows = [list(labels.headers)]
        for facilitator in facilitators:
            discount = discounts.get(facilitator.pk)
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
        return len(facilitators)
