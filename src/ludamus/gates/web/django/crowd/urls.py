from django.urls import URLPattern, URLResolver, include, path
from django.views.generic import RedirectView

from ludamus.gates.web.django.crowd import auth, profile, views

auth0_urlpatterns = [
    path("do/login", auth.Auth0LoginActionView.as_view(), name="login"),
    path(
        "do/login/callback",
        auth.Auth0LoginCallbackActionView.as_view(),
        name="login-callback",
    ),
    path("do/logout", auth.Auth0LogoutActionView.as_view(), name="logout"),
    path(
        "do/logout/redirect",
        auth.Auth0LogoutRedirectActionView.as_view(),
        name="logout-redirect",
    ),
]

urlpatterns: list[URLPattern | URLResolver] = [
    path("profile/parties/", views.PartiesPageView.as_view(), name="profile-parties"),
    path(
        "profile/parties/<int:pk>/",
        views.PartyDetailPageView.as_view(),
        name="party-detail",
    ),
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
        "profile/parties/<int:pk>/do/invite-link",
        views.PartyInviteLinkActionView.as_view(),
        name="parties-invite-link",
    ),
    path(
        "profile/parties/<int:pk>/do/add-companion",
        views.PartyCompanionAddActionView.as_view(),
        name="parties-add-companion",
    ),
    path(
        "parties/join/<str:token>/",
        views.PartyJoinPageView.as_view(),
        name="parties-join",
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
    path("auth0/", include((auth0_urlpatterns, "auth0"), namespace="auth0")),
    path(
        "login-required/", auth.LoginRequiredPageView.as_view(), name="login-required"
    ),
    path("profile/", profile.ProfilePageView.as_view(), name="profile"),
    path(
        "profile/avatar/",
        profile.ProfileAvatarPageView.as_view(),
        name="profile-avatar",
    ),
    path(
        "profile/shadowbans/",
        RedirectView.as_view(pattern_name="web:crowd:profile-safety", permanent=True),
    ),
    path(
        "profile/safety/",
        profile.ProfileShadowbanPageView.as_view(),
        name="profile-safety",
    ),
    path(
        "profile/companions/",
        profile.ProfileCompanionsPageView.as_view(),
        name="profile-companions",
    ),
    path(
        "profile/companions/<str:slug>/do/update",
        profile.ProfileCompanionUpdateActionView.as_view(),
        name="profile-companions-update",
    ),
    path(
        "profile/companions/<str:slug>/do/delete",
        profile.ProfileCompanionDeleteActionView.as_view(),
        name="profile-companions-delete",
    ),
    path(
        "profile/companions/<str:slug>/do/claim-link",
        profile.ProfileCompanionClaimLinkActionView.as_view(),
        name="profile-companions-claim-link",
    ),
    path("claim/<str:token>/", profile.ClaimPageView.as_view(), name="claim"),
]
