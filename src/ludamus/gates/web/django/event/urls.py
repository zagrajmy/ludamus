from django.db.transaction import non_atomic_requests
from django.urls import URLPattern, path

from ludamus.gates.web.django.event import propose, tickets

urlpatterns: list[URLPattern] = [
    path(
        "event/<str:event_slug>/session/propose/",
        propose.ProposeSessionPageView.as_view(),
        name="session-propose",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/category",
        propose.ProposeSessionCategoryComponentView.as_view(),
        name="session-propose-category",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/personal",
        propose.ProposeSessionPersonalComponentView.as_view(),
        name="session-propose-personal",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/timeslots",
        propose.ProposeSessionTimeslotsComponentView.as_view(),
        name="session-propose-timeslots",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/details",
        propose.ProposeSessionDetailsComponentView.as_view(),
        name="session-propose-details",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/review",
        propose.ProposeSessionReviewComponentView.as_view(),
        name="session-propose-review",
    ),
    path(
        "event/<str:event_slug>/session/propose/do/submit",
        propose.ProposeSessionSubmitActionView.as_view(),
        name="session-propose-submit",
    ),
    path(
        "event/<str:event_slug>/tickets/",
        tickets.EventTicketsPageView.as_view(),
        name="event-tickets",
    ),
    # SAFETY: non-atomic, so Checkout's seat hold commits, and releases the
    # event's lock, before the Stripe call it waits on.
    path(
        "event/<str:event_slug>/tickets/do/buy",
        non_atomic_requests(tickets.EventTicketsBuyActionView.as_view()),
        name="event-tickets-buy",
    ),
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/",
        tickets.EventTicketOrderPageView.as_view(),
        name="event-ticket-order",
    ),
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/do/cancel",
        non_atomic_requests(tickets.EventTicketOrderCancelActionView.as_view()),
        name="event-ticket-order-cancel",
    ),
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/do/claim",
        tickets.EventTicketOrderClaimActionView.as_view(),
        name="event-ticket-order-claim",
    ),
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/claim/<str:token>/",
        tickets.EventTicketOrderClaimConfirmPageView.as_view(),
        name="event-ticket-order-claim-confirm",
    ),
]
