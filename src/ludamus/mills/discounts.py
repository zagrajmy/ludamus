import math
from collections import defaultdict
from dataclasses import dataclass, replace
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
    from ludamus.pacts.legacy import (
        FacilitatorChangeLogData,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorDTO,
        FacilitatorRepositoryProtocol,
    )
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


@dataclass(frozen=True)
class _DiscountWrite:
    data: DiscountData
    pk: int | None = None  # None: the facilitator holds no discount yet


@dataclass(frozen=True)
class _FacilitatorChange:
    """What the sync decided for one facilitator, before anything is written."""

    facilitator_id: int
    accreditation_from: AccreditationType
    accreditation_to: AccreditationType
    # At most one of these: write the rule discount, withdraw the rule discount
    # the rules no longer justify, or — both unset — leave the facilitator's
    # discount alone, hand-assigned or absent.
    write: _DiscountWrite | None = None
    withdraw_pk: int | None = None

    @property
    def accreditation_moved(self) -> bool:
        return self.accreditation_to is not self.accreditation_from


def _plan(
    *,
    entry: DiscountRosterEntryDTO,
    load: FacilitatorScheduleRow | None,
    rules: list[DiscountRuleDTO],
) -> _FacilitatorChange:
    facilitator = entry.facilitator
    current = AccreditationType(facilitator.accreditation_type)
    target = _target_accreditation(current=current, scheduled=load is not None)
    rule = (
        _first_match(rules, load)
        if load and target is AccreditationType.CREATOR
        else None
    )
    held = entry.discount
    change = _FacilitatorChange(
        facilitator_id=facilitator.pk,
        accreditation_from=current,
        accreditation_to=target,
    )
    if rule is not None and (held is None or held.from_rules):
        write = _DiscountWrite(
            data=_rule_discount(facilitator_id=facilitator.pk, rule=rule),
            pk=held.pk if held else None,
        )
        return replace(change, write=write)
    if rule is None and held is not None and held.from_rules:
        return replace(change, withdraw_pk=held.pk)
    return change


def _sync_result(changes: list[_FacilitatorChange]) -> DiscountSyncResultDTO:
    moved = [change for change in changes if change.accreditation_moved]
    return DiscountSyncResultDTO(
        marked=sum(1 for c in moved if c.accreditation_to is AccreditationType.CREATOR),
        unmarked=sum(1 for c in moved if c.accreditation_to is AccreditationType.NONE),
        discounts_set=sum(1 for c in changes if c.write is not None),
        discounts_cleared=sum(1 for c in changes if c.withdraw_pk is not None),
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
        facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._discounts = discounts
        self._facilitators = facilitators
        self._rules = rules
        self._schedule = schedule
        self._facilitator_change_logs = facilitator_change_logs

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
        self, *, event_pk: int, user_id: int
    ) -> DiscountSyncResultDTO:
        """Mark scheduled facilitators as creators and apply the rule discounts."""
        with self._transaction.atomic():
            rules = self._rules.list_for_event(event_pk)
            loads = {
                row.facilitator_id: row
                for row in self._schedule.list_facilitator_schedule(event_pk)
            }
            changes = [
                _plan(entry=entry, load=loads.get(entry.facilitator.pk), rules=rules)
                for entry in _roster(
                    discounts=self._discounts,
                    facilitators=self._facilitators,
                    event_pk=event_pk,
                )
            ]
            self._write_accreditations(
                event_pk=event_pk, changes=changes, user_id=user_id
            )
            for change in changes:
                self._write_discount(event_pk=event_pk, change=change)
        return _sync_result(changes)

    def _write_accreditations(
        self, *, event_pk: int, changes: list[_FacilitatorChange], user_id: int
    ) -> None:
        """Move every facilitator whose accreditation changed, in one write each."""
        if not (moved := [c for c in changes if c.accreditation_moved]):
            return
        by_target: defaultdict[AccreditationType, list[int]] = defaultdict(list)
        for change in moved:
            by_target[change.accreditation_to].append(change.facilitator_id)
        for target, pks in by_target.items():
            self._facilitators.set_accreditation(
                event_id=event_pk, pks=pks, accreditation_type=target.value
            )
        logs: list[FacilitatorChangeLogData] = [
            {
                "event_id": event_pk,
                "facilitator_id": change.facilitator_id,
                "user_id": user_id,
                "changes": [
                    {
                        "field": "accreditation_type",
                        "field_id": None,
                        "old": change.accreditation_from.value,
                        "new": change.accreditation_to.value,
                    }
                ],
            }
            for change in moved
        ]
        self._facilitator_change_logs.create_many(logs)

    def _write_discount(self, *, event_pk: int, change: _FacilitatorChange) -> None:
        if change.write is not None:
            if change.write.pk is None:
                self._discounts.create(event_pk, change.write.data)
            else:
                self._discounts.update(change.write.pk, change.write.data)
        elif change.withdraw_pk is not None:
            self._discounts.soft_delete(change.withdraw_pk)

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
