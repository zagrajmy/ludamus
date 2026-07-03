from django.urls import URLPattern, URLResolver, include, path
from django.views.generic.base import TemplateView

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


auth0_urls = [
    path("do/login", views.Auth0LoginActionView.as_view(), name="login"),
    path(
        "do/login/callback",
        views.Auth0LoginCallbackActionView.as_view(),
        name="login-callback",
    ),
    path("do/logout", views.Auth0LogoutActionView.as_view(), name="logout"),
    path(
        "do/logout/redirect",
        views.Auth0LogoutRedirectActionView.as_view(),
        name="logout-redirect",
    ),
]

crowd_urls: list[URLPattern | URLResolver] = [
    *crowd_gate_urls,
    path("auth0/", include((auth0_urls, "auth0"), namespace="auth0")),
    path(
        "login-required/", views.LoginRequiredPageView.as_view(), name="login-required"
    ),
    path("profile/", views.ProfilePageView.as_view(), name="profile"),
    path(
        "profile/avatar/", views.ProfileAvatarPageView.as_view(), name="profile-avatar"
    ),
    path(
        "profile/shadowbans/",
        views.ProfileShadowbanPageView.as_view(),
        name="profile-shadowbans",
    ),
    path(
        "profile/connected-users/",
        views.ProfileConnectedUsersPageView.as_view(),
        name="profile-connected-users",
    ),
    path(
        "profile/connected-users/<str:slug>/do/update",
        views.ProfileConnectedUserUpdateActionView.as_view(),
        name="profile-connected-users-update",
    ),
    path(
        "profile/connected-users/<str:slug>/do/delete",
        views.ProfileConnectedUserDeleteActionView.as_view(),
        name="profile-connected-users-delete",
    ),
    path(
        "profile/connected-users/<str:slug>/do/claim-link",
        views.ProfileConnectedUserClaimLinkActionView.as_view(),
        name="profile-connected-users-claim-link",
    ),
    path("claim/<str:token>/", views.ClaimPageView.as_view(), name="claim"),
]

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
        views.ProposalAcceptPageView.as_view(),
        name="session-accept",
    ),
    path(
        "event/<str:event_slug>/anonymous/do/activate",
        views.EventAnonymousActivateActionView.as_view(),
        name="event-anonymous-activate",
    ),
    path(
        "event/<str:event_slug>/session/<int:session_id>/enrollment/anonymous",
        views.SessionEnrollmentAnonymousPageView.as_view(),
        name="session-enrollment-anonymous",
    ),
    path(
        "offer/<str:token>/claim/",
        views.SessionOfferClaimView.as_view(),
        name="offer-claim",
    ),
    path(
        "offer/<str:token>/decline/",
        views.SessionOfferDeclineView.as_view(),
        name="offer-decline",
    ),
    path(
        "anonymous/do/load",
        views.AnonymousLoadActionView.as_view(),
        name="anonymous-load",
    ),
    path(
        "anonymous/do/reset/",
        views.AnonymousResetActionView.as_view(),
        name="anonymous-reset",
    ),
]

urlpatterns = [
    path("", views.IndexRedirectView.as_view(), name="index"),
    path("events/", views.EventsPageView.as_view(), name="events"),
    path(
        "notifications/do/mark-read",
        views.NotificationsMarkReadView.as_view(),
        name="notifications-mark-read",
    ),
    path("design/", views.DesignPageView.as_view(), name="design"),
    path("dev/emails/", views.StagingEmailInboxView.as_view(), name="staging-emails"),
    path(
        "design/tailwind/",
        TemplateView.as_view(template_name="design_tailwind.html"),
        name="design-tailwind",
    ),
    path(
        "chronology/", include((chronology_urls, "chronology"), namespace="chronology")
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
