"""In-memory stand-ins for the ticket and plan repositories and Stripe.

The ticket type and order fakes share one `TicketBook`, so seats sold and held
are counted from the orders the way the real repository's query counts them,
and an order moves only from a status its `allowed_from` names.
"""

from datetime import UTC, datetime, timedelta
from itertools import count

from ludamus.pacts.billing import PlanKind, PlanSource, SpherePlanDTO
from ludamus.pacts.payment_api import AccountState, PaymentProviderError
from ludamus.pacts.tickets import (
    CHECKOUT_STATUSES,
    LEDGER_STATUSES,
    SETTLING_STATUSES,
    SOLD_STATUSES,
    CheckoutSessionDTO,
    OrderDTO,
    OrderLineDTO,
    OrderRowDTO,
    OrderStatus,
    OwnedTicketDTO,
    PaidTotalsDTO,
    PayoutAccountDTO,
    TicketDTO,
    TicketTypeDTO,
)
from tests.unit.factories import event_dto

SPHERE_ID = 1
EVENT_ID = 1
OTHER_EVENT_ID = 2
BUYER_ID = 10
OTHER_BUYER_ID = 11
ACCOUNT_ID = "acct_sphere"
NOW = datetime.now(tz=UTC)


def shop_event():
    return event_dto(
        pk=EVENT_ID,
        sphere_id=SPHERE_ID,
        start_time=NOW + timedelta(days=30),
        end_time=NOW + timedelta(days=31),
    )


class TicketBook:
    """What the ticket type and order fakes both read and write."""

    def __init__(self):
        self.event = shop_event()
        self.types: dict[int, TicketTypeDTO] = {}
        self.orders: dict[int, OrderDTO] = {}

    def seats(self, *, ticket_type_id, counts):
        return sum(
            line.quantity
            for order in self.orders.values()
            if counts(order)
            for line in order.lines
            if line.ticket_type_id == ticket_type_id
        )


class FakeTicketTypes:
    def __init__(self, book):
        self._book = book
        self._pks = count(1)

    def add(self, **overrides):
        pk = next(self._pks)
        defaults = {
            "pk": pk,
            "event_id": EVENT_ID,
            "name": f"Ticket {pk}",
            "description": "",
            "price": 5000,
            "currency": "pln",
            "quantity": None,
            "sales_start": None,
            "sales_end": None,
            "is_archived": False,
            "order": pk,
            "sold": 0,
            "held": 0,
        }
        row = TicketTypeDTO(**(defaults | overrides))
        self._book.types[row.pk] = row
        return row

    def _counted(self, row, holds_after):
        return row.model_copy(
            update={
                "sold": self._book.seats(
                    ticket_type_id=row.pk,
                    counts=lambda order: order.status in SOLD_STATUSES,
                ),
                "held": self._book.seats(
                    ticket_type_id=row.pk,
                    counts=lambda order: order.status in SETTLING_STATUSES
                    or (
                        order.status in CHECKOUT_STATUSES
                        and order.hold_until > holds_after
                    ),
                ),
            }
        )

    def list_for_event(self, *, event_id, holds_after, include_archived=False):
        return [
            self._counted(row, holds_after)
            for row in self._book.types.values()
            if row.event_id == event_id and (include_archived or not row.is_archived)
        ]

    def lock_for_event(self, *, event_id, holds_after):
        return self.list_for_event(event_id=event_id, holds_after=holds_after)

    def read(self, *, event_id, pk, holds_after):
        return next(
            (
                self._counted(row, holds_after)
                for row in self._book.types.values()
                if row.pk == pk and row.event_id == event_id
            ),
            None,
        )

    def create(self, data):
        return self.add(**data)

    def update(self, *, event_id, pk, data):
        return self._replace(event_id=event_id, pk=pk, changes=dict(data))

    def set_archived(self, *, event_id, pk, archived):
        return self._replace(
            event_id=event_id, pk=pk, changes={"is_archived": archived}
        )

    def _replace(self, *, event_id, pk, changes):
        row = self._book.types.get(pk)
        if row is None or row.event_id != event_id:
            return False
        self._book.types[pk] = row.model_copy(update=changes)
        return True

    def next_order(self, *, event_id):
        return 1 + max(
            (
                row.order
                for row in self._book.types.values()
                if row.event_id == event_id
            ),
            default=-1,
        )


class FakeOrders:
    def __init__(self, book):
        self._book = book
        self._pks = count(1)
        self._ticket_pks = count(1)

    def add(self, *, lines, **overrides):
        pk = next(self._pks)
        defaults = {
            "pk": pk,
            "event_id": EVENT_ID,
            "event_name": self._book.event.name,
            "event_slug": self._book.event.slug,
            "buyer_id": BUYER_ID,
            "buyer_name": "Buyer",
            "email": "buyer@example.com",
            "status": OrderStatus.PENDING,
            "currency": "pln",
            "platform_fee": 0,
            "stripe_account_id": ACCOUNT_ID,
            "stripe_checkout_session_id": "",
            "stripe_payment_intent_id": "",
            "hold_until": NOW + timedelta(minutes=31),
            "paid_at": None,
            "refunded_at": None,
            "creation_time": NOW,
            "tickets": [],
        }
        order_lines = [
            OrderLineDTO(
                ticket_type_id=line["ticket_type_id"],
                ticket_type_name=self._book.types[line["ticket_type_id"]].name,
                quantity=line["quantity"],
                unit_price=line["unit_price"],
            )
            for line in lines
        ]
        total = sum(line.subtotal for line in order_lines)
        order = OrderDTO(**(defaults | {"total": total} | overrides), lines=order_lines)
        self._book.orders[pk] = order
        return order

    def _update(self, pk, **changes):
        self._book.orders[pk] = self._book.orders[pk].model_copy(update=changes)

    def _find(self, matches):
        return next(
            (order for order in self._book.orders.values() if matches(order)), None
        )

    def create(self, data):
        fields = {key: value for key, value in data.items() if key != "lines"}
        return self.add(lines=data["lines"], **fields)

    def attach_checkout(self, *, pk, session_id):
        self._update(pk, stripe_checkout_session_id=session_id)

    def read_for_buyer(self, *, buyer_id, pk):
        return self._find(lambda order: order.pk == pk and order.buyer_id == buyer_id)

    def lock_for_event(self, *, event_id, pk):
        return self._find(lambda order: order.pk == pk and order.event_id == event_id)

    def lock_by_checkout(self, *, session_id):
        return self._find(lambda order: order.stripe_checkout_session_id == session_id)

    def lock_by_payment_intent(self, *, payment_intent_id):
        return self._find(
            lambda order: order.stripe_payment_intent_id == payment_intent_id
        )

    def list_for_event(self, *, event_id, limit):
        newest_first = sorted(
            self._book.orders.values(), key=lambda order: order.pk, reverse=True
        )
        return [
            OrderRowDTO(
                pk=order.pk,
                buyer_name=order.buyer_name,
                email=order.email,
                status=order.status,
                currency=order.currency,
                total=order.total,
                creation_time=order.creation_time,
                lines=order.lines,
            )
            for order in newest_first
            if order.event_id == event_id and order.status in LEDGER_STATUSES
        ][:limit]

    def paid_totals(self, *, event_id):
        paid = [
            order
            for order in self._book.orders.values()
            if order.event_id == event_id and order.status is OrderStatus.PAID
        ]
        return PaidTotalsDTO(
            orders=len(paid),
            tickets=sum(order.ticket_count for order in paid),
            gross=sum(order.total for order in paid),
            platform_fees=sum(order.platform_fee for order in paid),
        )

    def move(self, *, pk, to, allowed_from, changes):
        if self._book.orders[pk].status not in allowed_from:
            return False
        self._update(pk, status=to, **changes)
        return True

    def issue_tickets(self, *, order, codes):
        remaining = iter(codes)
        self._update(
            order.pk,
            tickets=[
                TicketDTO(
                    pk=next(self._ticket_pks),
                    code=next(remaining),
                    ticket_type_name=line.ticket_type_name,
                    is_void=False,
                )
                for line in order.lines
                for _ in range(line.quantity)
            ],
        )

    def void_tickets(self, *, order_pk):
        self._update(
            order_pk,
            tickets=[
                ticket.model_copy(update={"is_void": True})
                for ticket in self._book.orders[order_pk].tickets
            ],
        )

    def _valid_tickets(self, *, holder_id, belongs):
        return [
            (order, ticket)
            for order in self._book.orders.values()
            if order.status is OrderStatus.PAID
            and order.buyer_id == holder_id
            and belongs(order)
            for ticket in order.tickets
            if not ticket.is_void
        ]

    def count_valid_tickets(self, *, event_id, holder_id):
        return len(
            self._valid_tickets(
                holder_id=holder_id, belongs=lambda order: order.event_id == event_id
            )
        )

    def list_owned_tickets(self, *, sphere_id, holder_id):
        event = self._book.event
        return [
            OwnedTicketDTO(
                code=ticket.code,
                ticket_type_name=ticket.ticket_type_name,
                order_pk=order.pk,
                event_name=event.name,
                event_slug=event.slug,
                event_start=event.start_time,
                event_end=event.end_time,
            )
            for order, ticket in self._valid_tickets(
                holder_id=holder_id,
                belongs=lambda order: order.event_id == event.pk
                and event.sphere_id == sphere_id,
            )
        ]


class FakeAccounts:
    def __init__(self):
        self.rows: dict[int, PayoutAccountDTO] = {}

    def add(self, *, sphere_id=SPHERE_ID, **overrides):
        defaults = {
            "stripe_account_id": ACCOUNT_ID,
            "details_submitted": True,
            "charges_enabled": True,
            "payouts_enabled": True,
        }
        self.rows[sphere_id] = PayoutAccountDTO(**(defaults | overrides))
        return self.rows[sphere_id]

    def read(self, *, sphere_id):
        return self.rows.get(sphere_id)

    def create_or_read(self, *, sphere_id, stripe_account_id):
        return self.rows.setdefault(
            sphere_id,
            PayoutAccountDTO(
                stripe_account_id=stripe_account_id,
                details_submitted=False,
                charges_enabled=False,
                payouts_enabled=False,
            ),
        )

    def update_state(self, *, stripe_account_id, state):
        for sphere_id, account in self.rows.items():
            if account.stripe_account_id == stripe_account_id:
                self.rows[sphere_id] = account.model_copy(update=state.model_dump())
                return True
        return False


class FakePlans:
    def __init__(self):
        self.rows: dict[int, SpherePlanDTO] = {}

    def add(self, *, sphere_id=SPHERE_ID, **data):
        return self.save(sphere_id=sphere_id, data=data)

    def read(self, *, sphere_id):
        return self.rows.get(sphere_id)

    def save(self, *, sphere_id, data):
        current = self.rows.get(sphere_id) or SpherePlanDTO(
            sphere_id=sphere_id,
            kind=PlanKind.STANDARD,
            source=PlanSource.STRIPE,
            paid_until=None,
            stripe_customer_id="",
            stripe_subscription_id="",
        )
        self.rows[sphere_id] = current.model_copy(update=dict(data))
        return self.rows[sphere_id]

    def lock_by_customer(self, *, customer_id):
        return next(
            (
                plan
                for plan in self.rows.values()
                if customer_id and plan.stripe_customer_id == customer_id
            ),
            None,
        )


class FakeTicketPayments:
    """Stripe Connect as the ticket mills see it; `down` names calls it refuses."""

    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.down: set[str] = set()
        self.event = None
        self.account_state = AccountState(
            details_submitted=True, charges_enabled=True, payouts_enabled=True
        )
        self.refunded: list[str] = []

    def _answer(self, call):
        if call in self.down:
            raise PaymentProviderError(call)

    def create_account(self, *, sphere_id, email):
        return f"acct_new_{sphere_id}"

    def onboarding_url(self, *, account_id, refresh_url, return_url):
        return f"https://connect.stripe.test/{account_id}"

    def read_account(self, *, account_id):
        return self.account_state

    def create_checkout(self, request):
        self._answer("create_checkout")
        session_id = f"cs_{request.order_pk}"
        return CheckoutSessionDTO(
            id=session_id, url=f"https://checkout.stripe.test/{session_id}"
        )

    def expire_checkout(self, *, account_id, session_id):
        self._answer("expire_checkout")

    def refund(self, *, account_id, payment_intent_id):
        self._answer("refund")
        self.refunded.append(payment_intent_id)

    def refund_once(self, *, account_id, payment_intent_id):
        self._answer("refund_once")
        self.refunded.append(payment_intent_id)

    def parse_webhook(self, *, payload, signature):
        return self.event
