from django.urls import URLPattern, URLResolver, path

from ludamus.gates.web.django.board import views

urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.BoardPageView.as_view(), name="index"),
    path("mine/", views.MyListingsPageView.as_view(), name="mine"),
    path("create/", views.ListingCreatePageView.as_view(), name="create"),
    path("<int:pk>/", views.ListingDetailPageView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ListingEditPageView.as_view(), name="edit"),
    path(
        "<int:pk>/do/publish", views.ListingPublishActionView.as_view(), name="publish"
    ),
    path("<int:pk>/do/close", views.ListingCloseActionView.as_view(), name="close"),
    path("<int:pk>/do/reopen", views.ListingReopenActionView.as_view(), name="reopen"),
    path(
        "<int:pk>/do/respond", views.ListingRespondActionView.as_view(), name="respond"
    ),
    path(
        "<int:pk>/do/withdraw",
        views.ListingWithdrawActionView.as_view(),
        name="withdraw",
    ),
    path(
        "<int:pk>/responses/",
        views.ListingResponsesPageView.as_view(),
        name="responses",
    ),
    path(
        "<int:pk>/responses/<int:response_pk>/do/decline",
        views.ListingResponseDeclineActionView.as_view(),
        name="decline",
    ),
]
