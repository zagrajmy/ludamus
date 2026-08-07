"""URL patterns for the multiverse panel bounded context."""

from django.urls import path

from ludamus.gates.web.django.multiverse.panel.views import (
    announcements,
    connections,
    guilds,
    mcp_token,
    sphere_settings,
)

app_name = "panel"  # pylint: disable=invalid-name

urlpatterns = [
    path("", sphere_settings.SphereSettingsPageView.as_view(), name="sphere-settings"),
    path(
        "announcements/",
        announcements.AnnouncementsPageView.as_view(),
        name="announcements",
    ),
    path(
        "announcements/create/",
        announcements.AnnouncementCreatePageView.as_view(),
        name="announcement-create",
    ),
    path(
        "announcements/<int:pk>/edit/",
        announcements.AnnouncementEditPageView.as_view(),
        name="announcement-edit",
    ),
    path(
        "announcements/<int:pk>/do/delete/",
        announcements.AnnouncementDeletePageView.as_view(),
        name="announcement-delete",
    ),
    path("guilds/", guilds.GuildsPageView.as_view(), name="guilds"),
    path("guilds/create/", guilds.GuildCreatePageView.as_view(), name="guild-create"),
    path(
        "guilds/<int:pk>/edit/", guilds.GuildEditPageView.as_view(), name="guild-edit"
    ),
    path(
        "guilds/<int:pk>/do/delete/",
        guilds.GuildDeletePageView.as_view(),
        name="guild-delete",
    ),
    path(
        "guilds/<int:pk>/do/add-member",
        guilds.GuildMemberAddActionView.as_view(),
        name="guild-member-add",
    ),
    path(
        "guilds/<int:pk>/members/<int:membership_pk>/do/remove",
        guilds.GuildMemberRemoveActionView.as_view(),
        name="guild-member-remove",
    ),
    path("mcp/", mcp_token.OrganizerMcpTokenPageView.as_view(), name="mcp-token"),
    path("connections/", connections.ConnectionsPageView.as_view(), name="connections"),
    path(
        "connections/create/",
        connections.ConnectionCreatePageView.as_view(),
        name="connection-create",
    ),
    path(
        "connections/<int:pk>/edit/",
        connections.ConnectionEditPageView.as_view(),
        name="connection-edit",
    ),
    path(
        "connections/<int:pk>/do/delete/",
        connections.ConnectionDeletePageView.as_view(),
        name="connection-delete",
    ),
]
