from django.urls import URLPattern, URLResolver, path

from .oauth import McpAuthorizeView, McpTokenView
from .views import McpEndpointView, McpOrganizerEndpointView, McpTokenPageView

app_name = "mcp"  # pylint: disable=invalid-name

urlpatterns: list[URLPattern | URLResolver] = [
    path("", McpEndpointView.as_view(), name="endpoint"),
    path("organizer/", McpOrganizerEndpointView.as_view(), name="organizer-endpoint"),
    path("token/", McpTokenPageView.as_view(), name="token"),
    path("oauth/authorize/", McpAuthorizeView.as_view(), name="oauth-authorize"),
    path("oauth/token/", McpTokenView.as_view(), name="oauth-token"),
]
