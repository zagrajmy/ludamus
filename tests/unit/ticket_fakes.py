"""In-memory stand-ins for the ticket and plan repositories, Stripe and mail.

The ticket type and order fakes share one `TicketBook`, so seats sold and held
are counted from the orders the way the real repository's query counts them,
and an order moves only from a status its `allowed_from` names.

`tests.unit.ticket_fixtures` wires them into the ticket services.
"""

from datetime import UTC, datetime, timedelta
from itertools import count

from ludamus.pacts.billing import PlanSource, SpherePlanDTO
from ludamus.pacts.payment_api import AccountState, CheckoutEvent, PaymentProviderError
from ludamus.pacts.tickets import (
    CHECKOUT_STATUSES,
    LEDGER_STATUSES,
    SETTLING_STATUSES,
    SOLD_STATUSES,
    CheckoutRequest,
    CheckoutSessionDTO,
    ClaimConfirmationMail,
    OrderClaimPayload,
    OrderDTO,
    OrderLineDTO,
    OrderLinkMail,
    OrderMailError,
    OrderRowDTO,
    OrderStatus,
    OwnedTicketDTO,
    PaidTotalsDTO,
    PayoutAccountDTO,
    TicketDTO,
    TicketTypeDTO,
)
from tests.unit.factories import event_dto, user_dto

SPHERE_ID = 1
EVENT_ID = 1
OTHER_EVENT_ID = 2
BUYER_ID = 10
OTHER_BUYER_ID = 11
ACCOUNT_ID = "acct_sphere"
BUYER_EMAIL = "buyer@example.com"
GUEST_EMAIL = "guest@example.com"
PRICE = 5000
TICKETS_LOGGER = "ludamus.mills.tickets"
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
        # Not on `OrderDTO`: only the guest hold count reads it.
        self.guest_clients: dict[int, str] = {}
        # Not on `OrderDTO`: only the claim mail throttle reads it.
        self.claim_mailed_at: dict[int, datetime] = {}

    @staticmethod
    def holds_seats(order, *, holds_after):
        return order.status in SETTLING_STATUSES or (
            order.status in CHECKOUT_STATUSES and order.hold_until > holds_after
        )

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
            "price": PRICE,
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
                    counts=lambda order: self._book.holds_seats(
                        order, holds_after=holds_after
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

    def add(self, *, lines, guest_client="", **overrides):
        pk = next(self._pks)
        defaults = {
            "pk": pk,
            "reference": f"ref{pk}",
            "event_id": EVENT_ID,
            "event_name": self._book.event.name,
            "event_slug": self._book.event.slug,
            "buyer_id": BUYER_ID,
            "buyer_name": "Buyer",
            "email": BUYER_EMAIL,
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
        self._book.guest_clients[pk] = guest_client
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

    def read_by_reference(self, *, reference):
        return self._find(lambda order: order.reference == reference)

    def lock_by_reference(self, *, reference):
        return self.read_by_reference(reference=reference)

    def claim(self, *, pk, buyer_id):
        self._update(pk, buyer_id=buyer_id)
        self._book.guest_clients[pk] = ""

    def take_claim_mail_slot(self, *, pk, now, interval):
        mailed_at = self._book.claim_mailed_at.get(pk)
        if mailed_at is not None and mailed_at > now - interval:
            return False
        self._book.claim_mailed_at[pk] = now
        return True

    def release_claim_mail_slot(self, *, pk, taken_at):
        self._book.claim_mailed_at = {
            order_pk: stamp
            for order_pk, stamp in self._book.claim_mailed_at.items()
            if (order_pk, stamp) != (pk, taken_at)
        }

    def count_guest_holds(self, *, event_id, guest_client, holds_after):
        return sum(
            1
            for order in self._book.orders.values()
            if order.event_id == event_id
            and order.is_guest
            and self._book.guest_clients[order.pk] == guest_client
            and self._book.holds_seats(order, holds_after=holds_after)
        )

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
            if order.event_id == event_id and order.status in SOLD_STATUSES
        ]
        return PaidTotalsDTO(
            orders=len(paid),
            tickets=sum(order.ticket_count for order in paid),
            gross=sum(order.total for order in paid),
            platform_fees=sum(order.platform_fee for order in paid),
        )

    def move(self, *, pk, to, allowed_from, changes, forget_guest_client):
        if self._book.orders[pk].status not in allowed_from:
            return False
        if forget_guest_client:
            self._book.guest_clients[pk] = ""
        self._update(pk, status=to, **changes)
        return True

    def issue_tickets(self, *, order, tickets):
        names = {line.ticket_type_id: line.ticket_type_name for line in order.lines}
        self._update(
            order.pk,
            tickets=[
                TicketDTO(
                    pk=next(self._ticket_pks),
                    code=ticket["code"],
                    ticket_type_name=names[ticket["ticket_type_id"]],
                )
                for ticket in tickets
            ],
        )

    def _valid_tickets(self, *, holder_id, belongs):
        return [
            (order, ticket)
            for order in self._book.orders.values()
            if order.status in SOLD_STATUSES
            and order.buyer_id == holder_id
            and belongs(order)
            for ticket in order.tickets
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
                event_name=event.name,
                event_slug=event.slug,
                event_start=event.start_time,
            )
            for _order, ticket in self._valid_tickets(
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
        self.update(sphere_id=sphere_id, data=data)
        return self.rows[sphere_id]

    def read(self, *, sphere_id):
        return self.rows.get(sphere_id)

    def update(self, *, sphere_id, data):
        current = self.rows.get(sphere_id) or SpherePlanDTO(
            sphere_id=sphere_id,
            technical_partner=False,
            ticket_fee_bps=None,
            yearly_price=None,
            source=PlanSource.MANUAL,
            paid_until=None,
            stripe_customer_id="",
            stripe_subscription_id="",
        )
        self.rows[sphere_id] = current.model_copy(update=dict(data))

    def lock_by_customer(self, *, customer_id):
        return next(
            (
                plan
                for plan in self.rows.values()
                if customer_id and plan.stripe_customer_id == customer_id
            ),
            None,
        )


class FakeUsers:
    """Accounts: BUYER_ID verified its own address, OTHER_BUYER_ID not the guest's."""

    def __init__(self):
        self.rows = {}
        self.add(pk=BUYER_ID, email=BUYER_EMAIL, email_verified=True)
        self.add(pk=OTHER_BUYER_ID, email=GUEST_EMAIL, email_verified=False)

    def add(self, *, pk, email, email_verified):
        self.rows[pk] = user_dto(
            pk=pk, slug=f"user-{pk}", email=email, email_verified=email_verified
        )

    def read_by_id(self, pk):
        return self.rows[pk]


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
        self.checkouts: list[CheckoutRequest] = []

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
        self.checkouts.append(request)
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


class FakeMailer:
    """`down`: the mail server refuses claim confirmations."""

    def __init__(self):
        self.down = False
        self.sent: list[OrderLinkMail] = []
        self.confirmations: list[ClaimConfirmationMail] = []

    def send_order_link(self, mail):
        self.sent.append(mail)

    def send_claim_confirmation(self, mail):
        if self.down:
            raise OrderMailError
        self.confirmations.append(mail)


class FakeClaimCodec:
    """Signed claim links: a token reads back as its payload until it expires."""

    def __init__(self):
        self._issued: dict[str, OrderClaimPayload] = {}

    def dumps(self, payload):
        token = f"claim-{len(self._issued) + 1}"
        self._issued[token] = payload
        return token

    def loads(self, token):
        return self._issued.get(token)

    def expire(self, token):
        del self._issued[token]


def add_order(orders, ticket_type, *, quantity=2, **overrides):
    return orders.add(
        lines=[
            {
                "ticket_type_id": ticket_type.pk,
                "quantity": quantity,
                "unit_price": ticket_type.price,
            }
        ],
        **overrides,
    )


def add_guest_order(orders, ticket_type, **overrides):
    # A guest's address comes from Checkout: until then the order has none.
    return add_order(
        orders, ticket_type, **({"buyer_id": None, "email": ""} | overrides)
    )


def checkout_event(stage, *, session_id="cs_1", paid=True, email=""):
    return CheckoutEvent(
        stage=stage,
        session_id=session_id,
        paid=paid,
        payment_intent_id="pi_1",
        email=email,
    )


def deliver(sales, payments, event):
    payments.event = event
    return sales.handle_webhook(payload=b"{}", signature="sig")


def status_of(book, order):
    return book.orders[order.pk].status
