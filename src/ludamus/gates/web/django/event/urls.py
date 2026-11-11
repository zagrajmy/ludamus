from django.db.transaction import non_atomic_requests
from django.urls import URLPattern, path

from ludamus.gates.web.django.event import anonymous, propose, tickets, views
from ludamus.gates.web.django.event.session_modal import SessionModalComponentView

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
    # SAFETY: non-atomic, so the order's lock is released before the mail
    # server is waited on.
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/do/claim",
        non_atomic_requests(tickets.EventTicketOrderClaimActionView.as_view()),
        name="event-ticket-order-claim",
    ),
    path(
        "event/<str:event_slug>/tickets/orders/<slug:reference>/claim/<str:token>/",
        tickets.EventTicketOrderClaimConfirmPageView.as_view(),
        name="event-ticket-order-claim-confirm",
    ),
]

session_urlpatterns: list[URLPattern] = [
    path(
        "event/<str:event_slug>/session/<int:session_id>/edit/",
        views.SessionEditView.as_view(),
        name="session-edit",
    ),
    path(
        "event/<str:event_slug>/session/<int:session_id>/parts/modal",
        SessionModalComponentView.as_view(),
        name="session-modal",
    ),
    path(
        "event/<str:event_slug>/anonymous/do/activate",
        anonymous.EventAnonymousActivateActionView.as_view(),
        name="event-anonymous-activate",
    ),
    path(
        "event/<str:event_slug>/session/<int:session_id>/enrollment/anonymous",
        anonymous.SessionEnrollmentAnonymousPageView.as_view(),
        name="session-enrollment-anonymous",
    ),
    path(
        "anonymous/do/load",
        anonymous.AnonymousLoadActionView.as_view(),
        name="anonymous-load",
    ),
    path(
        "anonymous/do/reset/",
        anonymous.AnonymousResetActionView.as_view(),
        name="anonymous-reset",
    ),
    path(
        "session/<int:session_id>/bookmark/",
        views.SessionBookmarkToggleView.as_view(),
        name="session-bookmark",
    ),
]
