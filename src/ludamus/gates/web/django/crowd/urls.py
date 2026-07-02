from django.urls import path

from ludamus.gates.web.django.crowd import views

urlpatterns = [
    path("profile/parties/", views.PartiesPageView.as_view(), name="profile-parties"),
    path(
        "profile/parties/do/create",
        views.PartyCreateActionView.as_view(),
        name="parties-create",
    ),
    path(
        "profile/parties/<int:pk>/do/rename",
        views.PartyRenameActionView.as_view(),
        name="parties-rename",
    ),
    path(
        "profile/parties/<int:pk>/do/delete",
        views.PartyDeleteActionView.as_view(),
        name="parties-delete",
    ),
    path(
        "profile/parties/<int:pk>/do/invite",
        views.PartyInviteActionView.as_view(),
        name="parties-invite",
    ),
    path(
        "profile/parties/<int:pk>/do/consent",
        views.PartyConsentActionView.as_view(),
        name="parties-consent",
    ),
    path(
        "profile/parties/<int:pk>/do/leave",
        views.PartyLeaveActionView.as_view(),
        name="parties-leave",
    ),
    path(
        "profile/parties/<int:pk>/members/<int:membership_pk>/do/remove",
        views.PartyMemberRemoveActionView.as_view(),
        name="parties-member-remove",
    ),
    path(
        "profile/party-invites/<int:pk>/do/accept",
        views.PartyInviteAcceptActionView.as_view(),
        name="party-invites-accept",
    ),
    path(
        "profile/party-invites/<int:pk>/do/decline",
        views.PartyInviteDeclineActionView.as_view(),
        name="party-invites-decline",
    ),
]
