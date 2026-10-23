"""Repositories for ticket sales: ticket types, orders, tickets, payout accounts.

Panel reads are scoped to the event the panel resolved, buyer reads to the
buyer, so a pk from another event or another person matches nothing here.
Webhook reads go by Stripe's own ids, which only Stripe's signed payload names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.db.models import Max, Q, Sum

from ludamus.links.db.django.models import (
    PayoutAccount,
    Ticket,
    TicketOrder,
    TicketOrderLine,
    TicketType,
)
from ludamus.pacts.tickets import (
    OrderDTO,
    OrderLineDTO,
    OrderStatus,
    OwnedTicketDTO,
    PayoutAccountDTO,
    PayoutAccountRepositoryProtocol,
    TicketDTO,
    TicketOrderRepositoryProtocol,
    TicketTypeDTO,
    TicketTypeRepositoryProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet

    from ludamus.pacts.payment_api import AccountState
    from ludamus.pacts.tickets import (
        OrderCreateData,
        TicketTypeCreateData,
        TicketTypeData,
    )


class _OrderChanges(TypedDict, total=False):
    status: OrderStatus
    stripe_payment_intent_id: str
    paid_at: datetime
    refunded_at: datetime


_TICKET_TYPE_FIELDS = (
    "pk",
    "event_id",
    "name",
    "description",
    "price",
    "currency",
    "quantity",
    "sales_start",
    "sales_end",
    "is_archived",
    "order",
    "sold",
    "held",
)


def _held(holds_after: datetime) -> Q:
    return Q(order_lines__order__status=OrderStatus.AWAITING_PAYMENT) | Q(
        order_lines__order__status=OrderStatus.PENDING,
        order_lines__order__hold_until__gt=holds_after,
    )


def _with_counts(
    queryset: QuerySet[TicketType], holds_after: datetime
) -> QuerySet[TicketType]:
    return queryset.annotate(
        sold=Sum(
            "order_lines__quantity",
            filter=Q(order_lines__order__status=OrderStatus.PAID),
            default=0,
        ),
        held=Sum("order_lines__quantity", filter=_held(holds_after), default=0),
    )


def _counted(
    queryset: QuerySet[TicketType], holds_after: datetime
) -> list[TicketTypeDTO]:
    return [
        TicketTypeDTO.model_validate(row)
        for row in _with_counts(queryset, holds_after).values(*_TICKET_TYPE_FIELDS)
    ]


def _new_ticket_type_dto(ticket_type: TicketType) -> TicketTypeDTO:
    return TicketTypeDTO(
        pk=ticket_type.pk,
        event_id=ticket_type.event_id,
        name=ticket_type.name,
        description=ticket_type.description,
        price=ticket_type.price,
        currency=ticket_type.currency,
        quantity=ticket_type.quantity,
        sales_start=ticket_type.sales_start,
        sales_end=ticket_type.sales_end,
        is_archived=ticket_type.is_archived,
        order=ticket_type.order,
        sold=0,
        held=0,
    )


class TicketTypeRepository(TicketTypeRepositoryProtocol):
    @staticmethod
    def list_for_event(
        *, event_id: int, holds_after: datetime, include_archived: bool = False
    ) -> list[TicketTypeDTO]:
        queryset = TicketType.objects.filter(event_id=event_id)
        if not include_archived:
            queryset = queryset.filter(is_archived=False)
        return _counted(queryset.order_by("order", "pk"), holds_after)

    @staticmethod
    def lock_for_event(*, event_id: int, holds_after: datetime) -> list[TicketTypeDTO]:
        # Locked apart from the counting query: Postgres refuses FOR UPDATE on
        # an aggregate. Two buyers of the same event queue here, so the second
        # counts the first one's hold.
        list(
            TicketType.objects.select_for_update()
            .filter(event_id=event_id)
            .values_list("pk", flat=True)
        )
        return TicketTypeRepository.list_for_event(
            event_id=event_id, holds_after=holds_after
        )

    @staticmethod
    def read(*, event_id: int, pk: int, holds_after: datetime) -> TicketTypeDTO | None:
        found = _counted(
            TicketType.objects.filter(event_id=event_id, pk=pk), holds_after
        )
        return found[0] if found else None

    @staticmethod
    def create(data: TicketTypeCreateData) -> TicketTypeDTO:
        return _new_ticket_type_dto(TicketType.objects.create(**data))

    @staticmethod
    def update(*, event_id: int, pk: int, data: TicketTypeData) -> bool:
        return bool(TicketType.objects.filter(event_id=event_id, pk=pk).update(**data))

    @staticmethod
    def set_archived(*, event_id: int, pk: int, archived: bool) -> bool:
        return bool(
            TicketType.objects.filter(event_id=event_id, pk=pk).update(
                is_archived=archived
            )
        )

    @staticmethod
    def next_order(*, event_id: int) -> int:
        highest = TicketType.objects.filter(event_id=event_id).aggregate(
            highest=Max("order")
        )["highest"]
        return 0 if highest is None else highest + 1


def _orders() -> QuerySet[TicketOrder]:
    return TicketOrder.objects.select_related("event", "buyer").prefetch_related(
        "lines__ticket_type", "tickets__ticket_type"
    )


def _order_dto(order: TicketOrder) -> OrderDTO:
    return OrderDTO(
        pk=order.pk,
        event_id=order.event_id,
        event_name=order.event.name,
        event_slug=order.event.slug,
        buyer_id=order.buyer_id,
        buyer_name=order.buyer.name if order.buyer is not None else "",
        email=order.email,
        status=OrderStatus(order.status),
        currency=order.currency,
        total=order.total,
        platform_fee=order.platform_fee,
        stripe_account_id=order.stripe_account_id,
        stripe_checkout_session_id=order.stripe_checkout_session_id,
        stripe_payment_intent_id=order.stripe_payment_intent_id,
        hold_until=order.hold_until,
        paid_at=order.paid_at,
        refunded_at=order.refunded_at,
        creation_time=order.creation_time,
        lines=[
            OrderLineDTO(
                ticket_type_id=line.ticket_type_id,
                ticket_type_name=line.ticket_type.name,
                quantity=line.quantity,
                unit_price=line.unit_price,
            )
            for line in order.lines.all()
        ],
        tickets=[
            TicketDTO(
                pk=ticket.pk,
                code=ticket.code,
                ticket_type_name=ticket.ticket_type.name,
                is_void=ticket.is_void,
            )
            for ticket in order.tickets.all()
        ],
    )


def _read(queryset: QuerySet[TicketOrder]) -> OrderDTO | None:
    order = queryset.first()
    return None if order is None else _order_dto(order)


def _lock(queryset: QuerySet[TicketOrder]) -> OrderDTO | None:
    # The row lock first, on its own: FOR UPDATE does not mix with the
    # prefetches that build the DTO.
    pk = queryset.select_for_update().values_list("pk", flat=True).first()
    return None if pk is None else _read(_orders().filter(pk=pk))


def _move(
    *, pk: int, allowed_from: frozenset[OrderStatus], changes: _OrderChanges
) -> bool:
    return bool(
        TicketOrder.objects.filter(pk=pk, status__in=allowed_from).update(**changes)
    )


class TicketOrderRepository(TicketOrderRepositoryProtocol):
    @staticmethod
    def create(data: OrderCreateData) -> OrderDTO:
        fields = {key: value for key, value in data.items() if key != "lines"}
        order = TicketOrder.objects.create(**fields)
        TicketOrderLine.objects.bulk_create(
            TicketOrderLine(order=order, **line) for line in data["lines"]
        )
        return _order_dto(_orders().get(pk=order.pk))

    @staticmethod
    def attach_checkout(*, pk: int, session_id: str) -> None:
        TicketOrder.objects.filter(pk=pk).update(stripe_checkout_session_id=session_id)

    @staticmethod
    def read_for_buyer(*, buyer_id: int, pk: int) -> OrderDTO | None:
        return _read(_orders().filter(buyer_id=buyer_id, pk=pk))

    @staticmethod
    def lock_for_event(*, event_id: int, pk: int) -> OrderDTO | None:
        return _lock(TicketOrder.objects.filter(event_id=event_id, pk=pk))

    @staticmethod
    def lock_by_checkout(*, session_id: str) -> OrderDTO | None:
        if not session_id:
            return None
        return _lock(TicketOrder.objects.filter(stripe_checkout_session_id=session_id))

    @staticmethod
    def lock_by_payment_intent(*, payment_intent_id: str) -> OrderDTO | None:
        if not payment_intent_id:
            return None
        return _lock(
            TicketOrder.objects.filter(stripe_payment_intent_id=payment_intent_id)
        )

    @staticmethod
    def list_for_event(*, event_id: int) -> list[OrderDTO]:
        # Abandoned checkouts are noise in the panel; what was paid, refunded
        # or is still being paid is the ledger.
        return [
            _order_dto(order)
            for order in _orders().filter(
                event_id=event_id,
                status__in=(
                    OrderStatus.PAID,
                    OrderStatus.REFUNDED,
                    OrderStatus.AWAITING_PAYMENT,
                ),
            )
        ]

    @staticmethod
    def transition(
        *, pk: int, to: OrderStatus, allowed_from: frozenset[OrderStatus]
    ) -> bool:
        return _move(pk=pk, allowed_from=allowed_from, changes={"status": to})

    @staticmethod
    def mark_awaiting_payment(
        *, pk: int, payment_intent_id: str, allowed_from: frozenset[OrderStatus]
    ) -> bool:
        return _move(
            pk=pk,
            allowed_from=allowed_from,
            changes={
                "status": OrderStatus.AWAITING_PAYMENT,
                "stripe_payment_intent_id": payment_intent_id,
            },
        )

    @staticmethod
    def mark_paid(
        *,
        pk: int,
        payment_intent_id: str,
        paid_at: datetime,
        allowed_from: frozenset[OrderStatus],
    ) -> bool:
        return _move(
            pk=pk,
            allowed_from=allowed_from,
            changes={
                "status": OrderStatus.PAID,
                "stripe_payment_intent_id": payment_intent_id,
                "paid_at": paid_at,
            },
        )

    @staticmethod
    def mark_refunded(
        *, pk: int, refunded_at: datetime, allowed_from: frozenset[OrderStatus]
    ) -> bool:
        return _move(
            pk=pk,
            allowed_from=allowed_from,
            changes={"status": OrderStatus.REFUNDED, "refunded_at": refunded_at},
        )

    @staticmethod
    def issue_tickets(*, order: OrderDTO, codes: list[str]) -> None:
        remaining = iter(codes)
        Ticket.objects.bulk_create(
            Ticket(
                order_id=order.pk,
                ticket_type_id=line.ticket_type_id,
                holder_id=order.buyer_id,
                code=next(remaining),
            )
            for line in order.lines
            for _ in range(line.quantity)
        )

    @staticmethod
    def void_tickets(*, order_pk: int) -> None:
        Ticket.objects.filter(order_id=order_pk).update(is_void=True)

    @staticmethod
    def count_valid_tickets(*, event_id: int, holder_id: int) -> int:
        return Ticket.objects.filter(
            order__event_id=event_id,
            order__status=OrderStatus.PAID,
            holder_id=holder_id,
            is_void=False,
        ).count()

    @staticmethod
    def list_owned_tickets(*, sphere_id: int, holder_id: int) -> list[OwnedTicketDTO]:
        tickets = (
            Ticket.objects.filter(
                order__event__sphere_id=sphere_id,
                order__status=OrderStatus.PAID,
                holder_id=holder_id,
                is_void=False,
            )
            .select_related("ticket_type", "order__event")
            .order_by("order__event__start_time", "order_id", "pk")
        )
        return [
            OwnedTicketDTO(
                code=ticket.code,
                ticket_type_name=ticket.ticket_type.name,
                order_pk=ticket.order_id,
                event_name=ticket.order.event.name,
                event_slug=ticket.order.event.slug,
                event_start=ticket.order.event.start_time,
                event_end=ticket.order.event.end_time,
            )
            for ticket in tickets
        ]


class PayoutAccountRepository(PayoutAccountRepositoryProtocol):
    @staticmethod
    def read(*, sphere_id: int) -> PayoutAccountDTO | None:
        account = PayoutAccount.objects.filter(sphere_id=sphere_id).first()
        return None if account is None else PayoutAccountDTO.model_validate(account)

    @staticmethod
    def create_or_read(*, sphere_id: int, stripe_account_id: str) -> PayoutAccountDTO:
        # get_or_create absorbs the one-per-sphere race: of two managers
        # connecting at once, the second gets the first one's account.
        account, _ = PayoutAccount.objects.get_or_create(
            sphere_id=sphere_id, defaults={"stripe_account_id": stripe_account_id}
        )
        return PayoutAccountDTO.model_validate(account)

    @staticmethod
    def update_state(*, stripe_account_id: str, state: AccountState) -> bool:
        return bool(
            PayoutAccount.objects.filter(stripe_account_id=stripe_account_id).update(
                **state.model_dump()
            )
        )
