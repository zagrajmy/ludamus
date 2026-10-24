"""URL patterns for the multiverse subdomain."""

from django.urls import include, path

from ludamus.gates.web.django.sphere.team import JoinSpherePageView

app_name = "multiverse"  # pylint: disable=invalid-name

urlpatterns = [
    path(
        "panel/",
        include("ludamus.gates.web.django.multiverse.panel.urls", namespace="panel"),
    ),
    path("join/<str:token>/", JoinSpherePageView.as_view(), name="join"),
]
