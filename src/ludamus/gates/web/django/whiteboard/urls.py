from django.db.transaction import non_atomic_requests
from django.urls import URLPattern, URLResolver, path

from ludamus.gates.web.django.whiteboard import views

public_urlpatterns: list[URLPattern | URLResolver] = [
    path("<str:share_code>/", views.BoardPageView.as_view(), name="board"),
    path(
        "<str:share_code>/bootstrap/",
        views.BoardBootstrapEndpointView.as_view(),
        name="bootstrap",
    ),
]

authenticated_urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.BoardsPageView.as_view(), name="index"),
    path("do/create", views.BoardCreateActionView.as_view(), name="create"),
    path("<int:pk>/edit/", views.BoardEditPageView.as_view(), name="edit"),
    path(
        "<int:pk>/do/reset-link",
        views.BoardResetLinkActionView.as_view(),
        name="reset-link",
    ),
    # NOTE: the service commits the deletion itself before it calls the
    # Worker, so the Worker never wipes a board whose deletion rolls back.
    path(
        "<int:pk>/do/delete",
        non_atomic_requests(views.BoardDeleteActionView.as_view()),
        name="delete",
    ),
]
