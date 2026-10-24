"""Repositories for ticket sales: ticket types, orders, tickets, payout accounts.

Panel reads are scoped to the event the panel resolved, so a pk from another
event matches nothing here; a buyer's order is found by its secret reference,
and `mills.tickets` decides who may see it. Webhook reads go by Stripe's own
ids, which only Stripe's signed payload names.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce, Now
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.models import (
    Event,
    PayoutAccount,
    Ticket,
    TicketOrder,
    TicketOrderLine,
    TicketType,
)
from ludamus.pacts.tickets import (
    CHECKOUT_STATUSES,
    LEDGER_STATUSES,
    SETTLING_STATUSES,
    SOLD_STATUSES,
    OrderDTO,
    OrderLineDTO,
    OrderRowDTO,
    OrderStatus,
    OwnedTicketDTO,
    PaidTotalsDTO,
    PayoutAccountDTO,
    PayoutAccountRepositoryProtocol,
    TicketDTO,
    TicketMailerProtocol,
    TicketOrderRepositoryProtocol,
    TicketTypeDTO,
    TicketTypeRepositoryProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet

    from ludamus.pacts.payment_api import AccountState
    from ludamus.pacts.tickets import (
        NewTicketData,
        OrderChanges,
        OrderCreateData,
        OrderLinkMail,
        TicketTypeCreateData,
        TicketTypeData,
    )

logger = logging.getLogger(__name__)

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
    return Q(order_lines__order__status__in=SETTLING_STATUSES) | Q(
        order_lines__order__status__in=CHECKOUT_STATUSES,
        order_lines__order__hold_until__gt=holds_after,
    )


def _with_counts(
    queryset: QuerySet[TicketType], holds_after: datetime
) -> QuerySet[TicketType]:
    return queryset.annotate(
        sold=Sum(
            "order_lines__quantity",
            filter=Q(order_lines__order__status__in=SOLD_STATUSES),
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
        return bool(
            TicketType.objects.filter(event_id=event_id, pk=pk).update(
                **data, modification_time=Now()
            )
        )

    @staticmethod
    def set_archived(*, event_id: int, pk: int, archived: bool) -> bool:
        return bool(
            TicketType.objects.filter(event_id=event_id, pk=pk).update(
                is_archived=archived, modification_time=Now()
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


def _line_dtos(order: TicketOrder) -> list[OrderLineDTO]:
    return [
        OrderLineDTO(
            ticket_type_id=line.ticket_type_id,
            ticket_type_name=line.ticket_type.name,
            quantity=line.quantity,
            unit_price=line.unit_price,
        )
        for line in order.lines.all()
    ]


def _order_dto(order: TicketOrder) -> OrderDTO:
    return OrderDTO(
        pk=order.pk,
        reference=order.reference,
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
        lines=_line_dtos(order),
        tickets=[
            TicketDTO(
                pk=ticket.pk, code=ticket.code, ticket_type_name=ticket.ticket_type.name
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
        TicketOrder.objects.filter(pk=pk).update(
            stripe_checkout_session_id=session_id, modification_time=Now()
        )

    @staticmethod
    def read_by_reference(*, reference: str) -> OrderDTO | None:
        return _read(_orders().filter(reference=reference)) if reference else None

    @staticmethod
    def lock_by_reference(*, reference: str) -> OrderDTO | None:
        if not reference:
            return None
        return _lock(TicketOrder.objects.filter(reference=reference))

    @staticmethod
    def claim(*, pk: int, buyer_id: int) -> None:
        TicketOrder.objects.filter(pk=pk).update(
            buyer_id=buyer_id, modification_time=Now()
        )
        Ticket.objects.filter(order_id=pk).update(holder_id=buyer_id)

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
    def list_for_event(*, event_id: int, limit: int) -> list[OrderRowDTO]:
        # Abandoned checkouts are noise in the panel; what was paid, refunded
        # or is still being paid is the ledger.
        orders = (
            TicketOrder.objects.filter(event_id=event_id, status__in=LEDGER_STATUSES)
            .select_related("buyer")
            .prefetch_related("lines__ticket_type")[:limit]
        )
        return [
            OrderRowDTO(
                pk=order.pk,
                buyer_name=order.buyer.name if order.buyer is not None else "",
                email=order.email,
                status=OrderStatus(order.status),
                currency=order.currency,
                total=order.total,
                creation_time=order.creation_time,
                lines=_line_dtos(order),
            )
            for order in orders
        ]

    @staticmethod
    def paid_totals(*, event_id: int) -> PaidTotalsDTO:
        paid = TicketOrder.objects.filter(event_id=event_id, status__in=SOLD_STATUSES)
        sums = paid.aggregate(
            orders=Count("pk"),
            gross=Coalesce(Sum("total"), 0),
            platform_fees=Coalesce(Sum("platform_fee"), 0),
        )
        tickets = TicketOrderLine.objects.filter(order__in=paid).aggregate(
            tickets=Coalesce(Sum("quantity"), 0)
        )
        return PaidTotalsDTO.model_validate(sums | tickets)

    @staticmethod
    def move(
        *,
        pk: int,
        to: OrderStatus,
        allowed_from: frozenset[OrderStatus],
        changes: OrderChanges,
    ) -> bool:
        return bool(
            TicketOrder.objects.filter(pk=pk, status__in=allowed_from).update(
                status=to, modification_time=Now(), **changes
            )
        )

    @staticmethod
    def issue_tickets(*, order: OrderDTO, tickets: list[NewTicketData]) -> None:
        Ticket.objects.bulk_create(
            Ticket(
                order_id=order.pk,
                ticket_type_id=ticket["ticket_type_id"],
                holder_id=order.buyer_id,
                code=ticket["code"],
            )
            for ticket in tickets
        )

    @staticmethod
    def count_valid_tickets(*, event_id: int, holder_id: int) -> int:
        return Ticket.objects.filter(
            order__event_id=event_id,
            order__status__in=SOLD_STATUSES,
            holder_id=holder_id,
        ).count()

    @staticmethod
    def list_owned_tickets(*, sphere_id: int, holder_id: int) -> list[OwnedTicketDTO]:
        tickets = (
            Ticket.objects.filter(
                order__event__sphere_id=sphere_id,
                order__status__in=SOLD_STATUSES,
                holder_id=holder_id,
            )
            .select_related("ticket_type", "order__event")
            .order_by("order__event__start_time", "order__event_id", "order_id", "pk")
        )
        return [
            OwnedTicketDTO(
                code=ticket.code,
                ticket_type_name=ticket.ticket_type.name,
                event_name=ticket.order.event.name,
                event_slug=ticket.order.event.slug,
                event_start=ticket.order.event.start_time,
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
                **state.model_dump(), modification_time=Now()
            )
        )


class DjangoTicketMailer(TicketMailerProtocol):
    @staticmethod
    def send_order_link(mail: OrderLinkMail) -> None:
        domain = (
            Event.objects.filter(pk=mail.event_id)
            .values_list("sphere__site__domain", flat=True)
            .first()
        ) or str(settings.ROOT_DOMAIN)
        url = absolute_url(
            reverse(
                "web:event:event-ticket-order",
                kwargs={"event_slug": mail.event_slug, "reference": mail.reference},
            ),
            domain=domain,
        )
        subject = _("Your tickets for %(event)s") % {"event": mail.event_name}
        lines = [
            _("Thank you for your order. Your tickets and their QR codes are here:"),
            url,
            _("Anyone with this link can see the tickets, so keep it to yourself."),
        ]
        if mail.claimable:
            lines.append(
                _(
                    "To keep them in your Zagrajmy account, open the link and sign"
                    " in or create an account there."
                )
            )
        body = "\n\n".join(lines)

        def _send() -> None:
            try:
                EmailMessage(subject=subject, body=body, to=[mail.email]).send()
            except OSError:
                # The order page still works; the buyer has it open already.
                logger.exception("Order mail not sent: order=%s", mail.reference)

        # After commit: a rolled-back webhook must not mail a page that says
        # the order is still pending.
        transaction.on_commit(_send)
