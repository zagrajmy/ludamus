"""URL patterns for the multiverse panel bounded context."""

from django.urls import path

from ludamus.gates.web.django.multiverse.panel.views import (
    announcements,
    connections,
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
