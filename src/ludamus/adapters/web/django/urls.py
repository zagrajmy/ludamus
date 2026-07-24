from django.urls import URLPattern, URLResolver, include, path
from django.views.generic.base import RedirectView, TemplateView

from ludamus.gates.web.django.chronology import offers
from ludamus.gates.web.django.chronology import views as chronology_views
from ludamus.gates.web.django.chronology.urls import urlpatterns as chronology_gate_urls
from ludamus.gates.web.django.crowd.urls import urlpatterns as crowd_gate_urls
from ludamus.gates.web.django.notice_board.urls import (
    authenticated_urlpatterns as encounter_authenticated,
)
from ludamus.gates.web.django.notice_board.urls import (
    public_urlpatterns as encounter_public,
)

from . import views
from .print_views import PublicEventPrintView

app_name = "web"  # pylint: disable=invalid-name


crowd_urls: list[URLPattern | URLResolver] = [*crowd_gate_urls]

chronology_urls = [
    *chronology_gate_urls,
    path("event/<str:slug>/", views.EventPageView.as_view(), name="event"),
    path("event/<str:slug>/print/", PublicEventPrintView.as_view(), name="event-print"),
    path(
        "event/<str:event_slug>/session/<int:session_id>/enrollment/",
        views.SessionEnrollPageView.as_view(),
        name="session-enrollment",
    ),
    path(
        "event/<str:event_slug>/session/<int:session_id>/accept/",
        chronology_views.ProposalAcceptPageView.as_view(),
        name="session-accept",
    ),
    path(
        "offer/<str:token>/claim/",
        offers.SessionOfferClaimView.as_view(),
        name="offer-claim",
    ),
    path(
        "offer/<str:token>/decline/",
        offers.SessionOfferDeclineView.as_view(),
        name="offer-decline",
    ),
]

urlpatterns = [
    path("", views.IndexRedirectView.as_view(), name="index"),
    path("events/", views.EventsPageView.as_view(), name="events"),
    path(
        "notifications/do/mark-read",
        offers.NotificationsMarkReadView.as_view(),
        name="notifications-mark-read",
    ),
    path("design/", views.DesignPageView.as_view(), name="design"),
    path("brand/", TemplateView.as_view(template_name="brand.html"), name="brand"),
    path("dev/emails/", views.StagingEmailInboxView.as_view(), name="staging-emails"),
    path("", include((chronology_urls, "chronology"), namespace="chronology")),
    # Permanent redirects for links shared before the `chronology/` path segment
    # was dropped from public event URLs (issue #543, A4). View names are
    # unchanged, so only externally shared literal URLs need this shim.
    path(
        "chronology/<path:subpath>",
        RedirectView.as_view(url="/%(subpath)s", permanent=True, query_string=True),
        name="chronology-legacy-redirect",
    ),
    path("crowd/", include((crowd_urls, "crowd"), namespace="crowd")),
    path(
        "",
        include(
            (
                [
                    path("e/", include(encounter_public)),
                    path("encounters/", include(encounter_authenticated)),
                ],
                "notice-board",
            ),
            namespace="notice-board",
        ),
    ),
]
