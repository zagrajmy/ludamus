from django.urls import URLPattern, URLResolver, path

from .views import McpEndpointView, McpTokenPageView

app_name = "mcp"  # pylint: disable=invalid-name

urlpatterns: list[URLPattern | URLResolver] = [
    path("", McpEndpointView.as_view(), name="endpoint"),
    path("token/", McpTokenPageView.as_view(), name="token"),
]
