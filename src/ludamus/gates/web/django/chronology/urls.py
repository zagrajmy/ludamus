from django.urls import URLPattern, path

from . import views

urlpatterns: list[URLPattern] = [
    path(
        "event/<str:event_slug>/session/<int:session_id>/edit/",
        views.SessionEditPageView.as_view(),
        name="session-edit",
    ),
    path(
        "event/<str:event_slug>/session/propose/",
        views.ProposeSessionPageView.as_view(),
        name="session-propose",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/category",
        views.ProposeSessionCategoryComponentView.as_view(),
        name="session-propose-category",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/personal",
        views.ProposeSessionPersonalComponentView.as_view(),
        name="session-propose-personal",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/timeslots",
        views.ProposeSessionTimeslotsComponentView.as_view(),
        name="session-propose-timeslots",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/details",
        views.ProposeSessionDetailsComponentView.as_view(),
        name="session-propose-details",
    ),
    path(
        "event/<str:event_slug>/session/propose/parts/review",
        views.ProposeSessionReviewComponentView.as_view(),
        name="session-propose-review",
    ),
    path(
        "event/<str:event_slug>/session/propose/do/submit",
        views.ProposeSessionSubmitActionView.as_view(),
        name="session-propose-submit",
    ),
]
