from django.urls import URLPattern, path

from ludamus.gates.web.django.event.session_modal import SessionModalComponentView

from . import anonymous, views

urlpatterns: list[URLPattern] = [
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
