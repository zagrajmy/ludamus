# `urlpatterns` is the `user` namespace, where new profile pages land;
# `crowd_urlpatterns` is the legacy `web:crowd` one and shrinks as its pages
# move over.
from django.urls import URLPattern, URLResolver, include, path
from django.views.generic import RedirectView

from ludamus.gates.web.django import email_verification
from ludamus.gates.web.django.auth_pages import login_required_page
from ludamus.gates.web.django.user import auth, profile, views
from ludamus.gates.web.django.user.age_range import ProfileAgeRangePageView
from ludamus.gates.web.django.user.privacy import ProfilePrivacyPageView
from ludamus.gates.web.django.user.tickets import ProfileTicketsPageView

# No app_name here: the include() in gates/web/django/urls.py passes the
# namespace as a (module, app_namespace) tuple, which spares the module a
# lowercase "constant" pylint would otherwise flag.
urlpatterns = [
    path("profile/privacy/", ProfilePrivacyPageView.as_view(), name="profile-privacy"),
    path(
        "profile/privacy/age/",
        ProfileAgeRangePageView.as_view(),
        name="profile-age-range",
    ),
    path("profile/tickets/", ProfileTicketsPageView.as_view(), name="profile-tickets"),
]

auth0_urlpatterns = [
    path("do/login", auth.Auth0LoginActionView.as_view(), name="login"),
    path(
        "do/login/callback",
        auth.Auth0LoginCallbackActionView.as_view(),
        name="login-callback",
    ),
    path("signup/age", auth.Auth0SignupAgePageView.as_view(), name="signup-age"),
    path("do/logout", auth.Auth0LogoutActionView.as_view(), name="logout"),
    path(
        "do/logout/redirect",
        auth.Auth0LogoutRedirectActionView.as_view(),
        name="logout-redirect",
    ),
]

crowd_urlpatterns: list[URLPattern | URLResolver] = [
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
    path("login-required/", login_required_page, name="login-required"),
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
        "profile/notifications/",
        profile.ProfileNotificationsPageView.as_view(),
        name="profile-notifications",
    ),
    path(
        "profile/notifications/do/mention-mail",
        profile.ProfileMentionMailActionView.as_view(),
        name="profile-notifications-mention-mail",
    ),
    path(
        "profile/notifications/<int:pk>/do/mute",
        profile.ProfileNotificationsMuteActionView.as_view(),
        name="profile-notifications-mute",
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
    path(
        "email/link/<str:token>/",
        email_verification.EmailLinkPageView.as_view(),
        name="email-link",
    ),
    path(
        "profile/email/do/resend",
        email_verification.EmailResendActionView.as_view(),
        name="email-resend",
    ),
]
