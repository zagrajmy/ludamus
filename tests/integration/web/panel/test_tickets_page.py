"""The event panel's Tickets page: ticket types, takings, and refunds.

How it could go wrong: a non-manager edits prices or refunds; a ticket type or
order from another event is changed through this event's URLs; a price is
stored in złoty instead of grosze; a refund leaves Zagrajmy's fee behind or
the tickets valid; a refund Stripe refused is shown as done.
"""

from decimal import Decimal
from http import HTTPStatus
from urllib.parse import parse_qs

import pytest
import responses
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    SphereMembership,
    Ticket,
    TicketOrder,
    TicketType,
)
from ludamus.pacts.multiverse import SphereRole
from ludamus.pacts.tickets import (
    PayoutStatus,
    TicketPanelDTO,
    TicketSalesSummaryDTO,
    TicketTypeDTO,
)
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.stripe_helpers import (
    ACCOUNT_ID,
    API,
    connected_account,
    order,
    ticket_type,
)
from tests.integration.utils import (
    FormErrorsMatcher,
    FormInitialMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    READ_ONLY_ROLE_ERROR,
    assert_not_a_manager,
    panel_context,
)

pytestmark = pytest.mark.usefixtures("stripe_settings")


def _url(name, event, **kwargs):
    return reverse(name, kwargs={"slug": event.slug, **kwargs})


def _form_data(**overrides):
    return {
        "name": "Weekend pass",
        "description": "",
        "price": "49.99",
        "quantity": "",
        "sales_start": "",
        "sales_end": "",
    } | overrides


def _foreign_event():
    return EventFactory(sphere=SphereFactory(name="Elsewhere"), slug="elsewhere")


class TestTicketsPage:
    def test_redirects_anonymous_user_to_login(self, client, event):
        url = _url("panel:tickets", event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_refuses_a_stranger(self, authenticated_client, event):
        response = authenticated_client.get(_url("panel:tickets", event))

        assert_not_a_manager(response)

    def test_free_event_invites_a_first_ticket_type(self, panel_client, event):
        response = panel_client.get(_url("panel:tickets", event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/tickets.html",
            context_data={
                **panel_context(event, active_nav="tickets"),
                "page": TicketPanelDTO(
                    payout_status=PayoutStatus.NOT_CONNECTED,
                    payments_available=True,
                    platform_fee_percent=Decimal("3.5"),
                    rows=[],
                    archived=[],
                    summary=TicketSalesSummaryDTO(
                        orders=0,
                        tickets=0,
                        gross=0,
                        platform_fees=0,
                        estimated_stripe_fees=0,
                    ),
                    orders=[],
                    more_orders=False,
                ),
            },
        )

    def test_totals_count_paid_orders_only(self, panel_client, event, active_user):
        connected_account(event.sphere)
        kind = ticket_type(event, price=5000)
        order(event, buyer=active_user, lines=[(kind, 3)], status="paid")
        order(event, buyer=active_user, lines=[(kind, 1)], session_id="cs_2")

        response = panel_client.get(_url("panel:tickets", event))

        page = response.context_data["page"]
        # 150,00 zł: 3.5% is 5,25 zł; Stripe's 2.9% + 0,30 is 4,65 zł.
        assert page.summary == TicketSalesSummaryDTO(
            orders=1,
            tickets=3,
            gross=15_000,
            platform_fees=525,
            estimated_stripe_fees=465,
        )
        assert [row.ticket_type.held for row in page.rows] == [1]

    def test_long_ledger_lists_the_newest_and_totals_them_all(
        self, panel_client, event, active_user, monkeypatch
    ):
        monkeypatch.setattr("ludamus.mills.tickets.PANEL_ORDERS_SHOWN", 2)
        connected_account(event.sphere)
        kind = ticket_type(event, price=5000)
        placed = [
            order(
                event,
                buyer=active_user,
                lines=[(kind, 1)],
                status="paid",
                session_id=f"cs_{number}",
            )
            for number in range(3)
        ]

        response = panel_client.get(_url("panel:tickets", event))

        page = response.context_data["page"]
        assert [row.pk for row in page.orders] == [placed[2].pk, placed[1].pk]
        assert page.more_orders
        assert (page.summary.orders, page.summary.gross) == (3, 15_000)


class TestTicketTypeCreate:
    def test_stores_the_price_in_grosze(self, panel_client, event):
        response = panel_client.post(
            _url("panel:ticket-type-create", event), _form_data(quantity="300")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[(messages.SUCCESS, "Ticket type added.")],
        )
        created = TicketType.objects.get()
        assert (created.event_id, created.name, created.price, created.quantity) == (
            event.pk,
            "Weekend pass",
            4999,
            300,
        )

    @pytest.mark.parametrize(
        ("overrides", "errors"),
        (
            pytest.param(
                {"price": "1.99"},
                {"price": ["Ensure this value is greater than or equal to 2.00."]},
                id="below-stripes-minimum",
            ),
            pytest.param(
                {"price": "100000.00"},
                {"price": ["Ensure this value is less than or equal to 99999.99."]},
                id="a-full-order-over-stripes-maximum",
            ),
            pytest.param(
                {"sales_start": "2026-11-02T10:00", "sales_end": "2026-11-01T10:00"},
                {"sales_end": ["Sales have to close after they open."]},
                id="closes-before-it-opens",
            ),
        ),
    )
    def test_rejects_what_cannot_be_sold(self, panel_client, event, overrides, errors):
        response = panel_client.post(
            _url("panel:ticket-type-create", event), _form_data(**overrides)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/ticket-type-form.html",
            context_data={
                **panel_context(event, active_nav="tickets"),
                "form": FormErrorsMatcher(**errors),
                "ticket_type": None,
            },
        )
        assert not TicketType.objects.exists()

    def test_comms_member_cannot_add_one(self, client, active_user, sphere, event):
        SphereMembership.objects.create(
            sphere=sphere, user=active_user, role=SphereRole.COMMS
        )
        client.force_login(active_user)

        response = client.post(_url("panel:ticket-type-create", event), _form_data())

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/",
            messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        )
        assert not TicketType.objects.exists()


class TestTicketTypeEditAndArchive:
    def test_type_of_another_event_is_not_found(self, panel_client, event):
        theirs = ticket_type(_foreign_event())

        response = panel_client.post(
            _url("panel:ticket-type-edit", event, pk=theirs.pk),
            _form_data(price="2.00"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[(messages.ERROR, "Ticket type not found.")],
        )
        unchanged = theirs.price
        theirs.refresh_from_db()
        assert theirs.price == unchanged

    def test_edit_shows_the_price_in_zloty(self, panel_client, event):
        kind = ticket_type(event, price=4999)

        response = panel_client.get(_url("panel:ticket-type-edit", event, pk=kind.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/ticket-type-form.html",
            context_data={
                **panel_context(event, active_nav="tickets"),
                "form": FormInitialMatcher(price=4999),
                "ticket_type": TicketTypeDTO(
                    pk=kind.pk,
                    event_id=event.pk,
                    name=kind.name,
                    description="",
                    price=4999,
                    currency="pln",
                    quantity=None,
                    sales_start=None,
                    sales_end=None,
                    is_archived=False,
                    order=0,
                    sold=0,
                    held=0,
                ),
            },
        )

    def test_archive_takes_it_off_sale(self, panel_client, event):
        kind = ticket_type(event)

        response = panel_client.post(
            _url("panel:ticket-type-archive", event, pk=kind.pk)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[
                (
                    messages.SUCCESS,
                    "Ticket type taken off sale. Tickets already sold stay valid.",
                )
            ],
        )
        kind.refresh_from_db()
        assert kind.is_archived


class TestRefund:
    @pytest.fixture(name="paid")
    def paid_fixture(self, event, active_user):
        connected_account(event.sphere)
        kind = ticket_type(event)
        paid = order(
            event,
            buyer=UserFactory(),
            lines=[(kind, 2)],
            status="paid",
            payment_intent_id="pi_test_1",
        )
        Ticket.objects.create(order=paid, ticket_type=kind, code="ABCDEFGH23")
        return paid

    def test_refunds_through_stripe_including_zagrajmys_fee(
        self, panel_client, event, paid, stripe_api
    ):
        stripe_api.add(
            responses.POST, f"{API}/refunds", json={"id": "re_1", "object": "refund"}
        )

        response = panel_client.post(
            _url("panel:ticket-order-refund", event, pk=paid.pk)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Order refunded. The buyer gets the money back in 5–10 days"
                        " and the tickets no longer admit anyone."
                    ),
                )
            ],
        )
        request = stripe_api.calls[0].request
        assert request.headers["Stripe-Account"] == ACCOUNT_ID
        assert parse_qs(request.body) == {
            "payment_intent": ["pi_test_1"],
            "refund_application_fee": ["true"],
        }
        paid.refresh_from_db()
        assert paid.status == "refunded"
        assert not Ticket.objects.filter(order=paid, is_void=False).exists()

    def test_refused_refund_changes_nothing(
        self, panel_client, event, paid, stripe_api
    ):
        stripe_api.add(
            responses.POST,
            f"{API}/refunds",
            json={"error": {"type": "invalid_request_error", "message": "no"}},
            status=HTTPStatus.BAD_REQUEST,
        )

        response = panel_client.post(
            _url("panel:ticket-order-refund", event, pk=paid.pk)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[
                (
                    messages.ERROR,
                    (
                        "Stripe didn't accept the refund. Try again, or refund the"
                        " payment from your Stripe dashboard."
                    ),
                )
            ],
        )
        paid.refresh_from_db()
        assert paid.status == "paid"

    def test_order_of_another_event_is_not_found(
        self, panel_client, event, active_user, stripe_api
    ):
        elsewhere = _foreign_event()
        theirs = order(
            elsewhere,
            buyer=active_user,
            lines=[(ticket_type(elsewhere), 1)],
            status="paid",
            payment_intent_id="pi_x",
        )

        response = panel_client.post(
            _url("panel:ticket-order-refund", event, pk=theirs.pk)
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url("panel:tickets", event),
            messages=[(messages.ERROR, "Order not found.")],
        )
        assert not stripe_api.calls
        assert TicketOrder.objects.get(pk=theirs.pk).status == "paid"
