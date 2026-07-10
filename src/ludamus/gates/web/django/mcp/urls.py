from django.urls import URLPattern, URLResolver, path

from .views import McpEndpointView, McpOrganizerEndpointView, McpTokenPageView

app_name = "mcp"  # pylint: disable=invalid-name

urlpatterns: list[URLPattern | URLResolver] = [
    path("", McpEndpointView.as_view(), name="endpoint"),
    path("organizer/", McpOrganizerEndpointView.as_view(), name="organizer-endpoint"),
    path("token/", McpTokenPageView.as_view(), name="token"),
]
