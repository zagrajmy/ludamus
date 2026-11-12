from django.urls import URLPattern, path

from ludamus.gates.web.django.event import anonymous, propose, views
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
        "event/<str:event_slug>/session/propose/parts/days",
        propose.ProposeSessionDaysComponentView.as_view(),
        name="session-propose-days",
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
