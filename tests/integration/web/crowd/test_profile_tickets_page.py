"""My tickets: the codes the signed-in person holds for this sphere's events.

How it could go wrong: someone else's codes are shown; a refunded order's void
codes still look valid; codes from another sphere's events leak in.
"""

from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import Ticket
from ludamus.pacts.tickets import OwnedTicketDTO
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.stripe_helpers import order, ticket_type
from tests.integration.utils import assert_login_required, assert_response

URL = reverse("user:profile-tickets")


def _issued(event, *, holder, code, status="paid", session_id=None, is_void=False):
    kind = ticket_type(event)
    placed = order(
        event,
        buyer=holder,
        lines=[(kind, 1)],
        status=status,
        session_id=session_id or f"cs_{code}",
    )
    Ticket.objects.create(
        order=placed, ticket_type=kind, holder=holder, code=code, is_void=is_void
    )
    return placed


class TestProfileTicketsPageView:
    def test_redirects_anonymous_user_to_login(self, client):
        response = client.get(URL)

        assert_login_required(response, URL)

    def test_without_tickets_the_list_is_empty(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/user/tickets.html",
            context_data={"profile_active_tab": "tickets", "tickets": []},
        )

    def test_lists_only_the_viewers_valid_tickets_in_this_sphere(
        self, authenticated_client, event, active_user
    ):
        mine = _issued(event, holder=active_user, code="MINE222222")
        _issued(
            event,
            holder=active_user,
            code="VOID222222",
            status="refunded",
            is_void=True,
        )
        _issued(event, holder=UserFactory(), code="THEIRS2222")
        _issued(
            EventFactory(sphere=SphereFactory(name="Elsewhere")),
            holder=active_user,
            code="AWAY222222",
        )

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="crowd/user/tickets.html",
            context_data={
                "profile_active_tab": "tickets",
                "tickets": [
                    OwnedTicketDTO(
                        code="MINE222222",
                        ticket_type_name="Weekend pass",
                        order_pk=mine.pk,
                        event_name=event.name,
                        event_slug=event.slug,
                        event_start=event.start_time,
                        event_end=event.end_time,
                    )
                ],
            },
        )
