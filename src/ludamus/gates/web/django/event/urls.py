from django.urls import URLPattern, path

from ludamus.gates.web.django.event import propose

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
        "event/<str:event_slug>/session/propose/parts/spot",
        propose.ProposeSessionSpotComponentView.as_view(),
        name="session-propose-spot",
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
