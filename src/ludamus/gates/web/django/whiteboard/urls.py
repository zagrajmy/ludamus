from django.urls import URLPattern, URLResolver, path

from ludamus.gates.web.django.whiteboard import views

public_urlpatterns: list[URLPattern | URLResolver] = [
    path("<str:share_code>/", views.BoardPageView.as_view(), name="board")
]

authenticated_urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.BoardsPageView.as_view(), name="index"),
    path("new/", views.BoardCreatePageView.as_view(), name="create"),
    path("<int:pk>/edit/", views.BoardEditPageView.as_view(), name="edit"),
    path("<int:pk>/do/delete", views.BoardDeleteActionView.as_view(), name="delete"),
]
