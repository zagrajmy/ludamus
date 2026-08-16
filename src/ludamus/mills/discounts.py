import math
from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountKind,
    DiscountMethod,
    DiscountRosterEntryDTO,
    DiscountsExportServiceProtocol,
    DiscountsServiceProtocol,
    DiscountSyncResultDTO,
)
from ludamus.pacts.durations import MINUTES_PER_HOUR
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from ludamus.pacts.discounts import (
        AccreditationWriterProtocol,
        DiscountDTO,
        DiscountExportLabels,
        DiscountRepositoryProtocol,
        DiscountRuleData,
        DiscountRuleDTO,
        DiscountRuleRepositoryProtocol,
        FacilitatorScheduleRow,
        ScheduledProgramRepositoryProtocol,
        SheetWriterProtocol,
    )
    from ludamus.pacts.legacy import FacilitatorDTO, FacilitatorRepositoryProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


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


def _measure(*, rule: DiscountRuleDTO, load: FacilitatorScheduleRow) -> int:
    if rule.method is DiscountMethod.SESSION_COUNT:
        return load.session_count
    # Started hours: a facilitator scheduled for 1 h 50 min has started two.
    return math.ceil(load.minutes / MINUTES_PER_HOUR)


def _rule_order(rule: DiscountRuleDTO) -> tuple[int, int]:
    return rule.order, rule.pk


def _first_match(
    rules: list[DiscountRuleDTO], load: FacilitatorScheduleRow
) -> DiscountRuleDTO | None:
    return next(
        (rule for rule in rules if _measure(rule=rule, load=load) >= rule.quantity),
        None,
    )


def _target_accreditation(
    *, current: AccreditationType, scheduled: bool
) -> AccreditationType:
    # Guest, honorary and standard are somebody's decision about a person; the
    # sync owns the none <-> creator pair and nothing else.
    if scheduled and current is AccreditationType.NONE:
        return AccreditationType.CREATOR
    if not scheduled and current is AccreditationType.CREATOR:
        return AccreditationType.NONE
    return current


def _rule_discount(*, facilitator_id: int, rule: DiscountRuleDTO) -> DiscountData:
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=rule.percent,
        from_rules=True,
    )


class DiscountsService(DiscountsServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        discounts: DiscountRepositoryProtocol,
        facilitators: FacilitatorRepositoryProtocol,
        rules: DiscountRuleRepositoryProtocol,
        schedule: ScheduledProgramRepositoryProtocol,
        accreditation: AccreditationWriterProtocol,
    ) -> None:
        self._transaction = transaction
        self._discounts = discounts
        self._facilitators = facilitators
        self._rules = rules
        self._schedule = schedule
        self._accreditation = accreditation

    def list_roster(self, event_pk: int) -> list[DiscountRosterEntryDTO]:
        return _roster(
            discounts=self._discounts,
            facilitators=self._facilitators,
            event_pk=event_pk,
        )

    def list_rules(self, event_pk: int) -> list[DiscountRuleDTO]:
        return self._rules.list_for_event(event_pk)

    def read_rule(self, event_pk: int, pk: int) -> DiscountRuleDTO | None:
        return self._rules.read(event_pk, pk)

    def create_rule(self, event_pk: int, data: DiscountRuleData) -> DiscountRuleDTO:
        with self._transaction.atomic():
            return self._rules.create(event_pk, data)

    def update_rule(
        self, *, event_pk: int, pk: int, data: DiscountRuleData
    ) -> DiscountRuleDTO | None:
        with self._transaction.atomic():
            return self._rules.update(event_id=event_pk, pk=pk, data=data)

    def delete_rule(self, event_pk: int, pk: int) -> bool:
        with self._transaction.atomic():
            return self._rules.delete(event_pk, pk)

    def apply_from_agenda(
        self, *, event_pk: int, user_id: int | None = None
    ) -> DiscountSyncResultDTO:
        """Mark scheduled facilitators as creators and apply the rule discounts."""
        marked = unmarked = discounts_set = discounts_cleared = 0
        with self._transaction.atomic():
            rules = sorted(self._rules.list_for_event(event_pk), key=_rule_order)
            loads = {
                row.facilitator_id: row
                for row in self._schedule.list_facilitator_schedule(event_pk)
            }
            for entry in _roster(
                discounts=self._discounts,
                facilitators=self._facilitators,
                event_pk=event_pk,
            ):
                facilitator = entry.facilitator
                load = loads.get(facilitator.pk)
                current = AccreditationType(facilitator.accreditation_type)
                target = _target_accreditation(
                    current=current, scheduled=load is not None
                )
                if target is not current:
                    self._accreditation.set_accreditation(
                        event_id=event_pk,
                        facilitator_slug=facilitator.slug,
                        accreditation_type=target.value,
                        user_id=user_id,
                    )
                    if target is AccreditationType.CREATOR:
                        marked += 1
                    else:
                        unmarked += 1
                match = (
                    _first_match(rules, load)
                    if load and target is AccreditationType.CREATOR
                    else None
                )
                discounts_set += self._apply_rule_discount(
                    event_pk=event_pk,
                    facilitator_id=facilitator.pk,
                    current=entry.discount,
                    rule=match,
                )
                discounts_cleared += self._clear_rule_discount(
                    current=entry.discount, rule=match
                )
        return DiscountSyncResultDTO(
            marked=marked,
            unmarked=unmarked,
            discounts_set=discounts_set,
            discounts_cleared=discounts_cleared,
        )

    def _apply_rule_discount(
        self,
        *,
        event_pk: int,
        facilitator_id: int,
        current: DiscountDTO | None,
        rule: DiscountRuleDTO | None,
    ) -> int:
        if rule is None or (current is not None and not current.from_rules):
            return 0
        data = _rule_discount(facilitator_id=facilitator_id, rule=rule)
        if current is None:
            self._discounts.create(event_pk, data)
        else:
            self._discounts.update(current.pk, data)
        return 1

    def _clear_rule_discount(
        self, *, current: DiscountDTO | None, rule: DiscountRuleDTO | None
    ) -> int:
        if rule is not None or current is None or not current.from_rules:
            return 0
        self._discounts.soft_delete(current.pk)
        return 1

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
        tab_title: str,
        labels: DiscountExportLabels,
    ) -> int:
        # `read_secret` raises NotFoundError for a connection outside the
        # sphere, so a forged connection id cannot borrow another sphere's
        # credentials.
        blob = self._connections.read_secret(sphere_id, connection_id)
        secret = self._decryptor.decrypt(blob) if blob else b""
        # Accreditation "none" means the person gets nothing at the desk, so
        # they have no line on the accreditation sheet either.
        entries = [
            entry
            for entry in _roster(
                discounts=self._discounts,
                facilitators=self._facilitators,
                event_pk=event_pk,
            )
            if entry.facilitator.accreditation_type != AccreditationType.NONE
        ]
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
            secret=secret, spreadsheet_id=spreadsheet_id, tab_title=tab_title, rows=rows
        )
        return len(entries)
