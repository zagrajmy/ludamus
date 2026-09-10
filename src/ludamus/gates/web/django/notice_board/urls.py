from django.urls import URLPattern, URLResolver, path

from . import views

public_urlpatterns: list[URLPattern | URLResolver] = [
    path(
        "<str:share_code>/",
        views.EncounterDetailPageView.as_view(),
        name="encounter-detail",
    ),
    path(
        "<str:share_code>/qr.svg", views.EncounterQrView.as_view(), name="encounter-qr"
    ),
    path(
        "<str:share_code>/calendar.ics",
        views.EncounterIcsView.as_view(),
        name="encounter-ics",
    ),
]

authenticated_urlpatterns: list[URLPattern | URLResolver] = [
    path("create/", views.EncounterCreatePageView.as_view(), name="create"),
    path("<int:pk>/edit/", views.EncounterEditPageView.as_view(), name="edit"),
    path(
        "<int:pk>/do/delete", views.EncounterDeleteActionView.as_view(), name="delete"
    ),
    path(
        "<str:share_code>/do/rsvp",
        views.EncounterRSVPActionView.as_view(),
        name="encounter-rsvp",
    ),
    path(
        "<str:share_code>/do/cancel-rsvp",
        views.EncounterCancelRSVPActionView.as_view(),
        name="encounter-cancel-rsvp",
    ),
]
