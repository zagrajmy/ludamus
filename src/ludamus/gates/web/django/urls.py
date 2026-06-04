"""URL configuration for gates/web/django views."""

import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.cache import never_cache

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.urls import URLPattern, URLResolver


handler404 = (  # pylint: disable=invalid-name
    "ludamus.adapters.web.django.error_views.custom_404"
)
handler500 = (  # pylint: disable=invalid-name
    "ludamus.adapters.web.django.error_views.custom_500"
)

_HEALTHZ_INTERVAL = 5
_healthz_cache: dict[str, object] = {"time": 0.0, "ok": True}


@never_cache
def healthz(request: HttpRequest) -> JsonResponse:  # noqa: ARG001
    now = time.monotonic()
    if now - _healthz_cache["time"] < _HEALTHZ_INTERVAL:  # type: ignore[operator]
        if _healthz_cache["ok"]:
            return JsonResponse({"status": "ok"})
        return JsonResponse({"status": "error"}, status=503)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        _healthz_cache.update(time=now, ok=True)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        _healthz_cache.update(time=now, ok=False)
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns: list[URLResolver | URLPattern] = [
    path("healthz/", healthz),
    path("", include("ludamus.adapters.web.django.urls", namespace="web")),
    path(
        "panel/",
        include("ludamus.gates.web.django.chronology.panel.urls", namespace="panel"),
    ),
    path(
        "multiverse/",
        include("ludamus.gates.web.django.multiverse.urls", namespace="multiverse"),
    ),
    path("admin/", admin.site.urls),
    path("page/", include("django.contrib.flatpages.urls")),
]


if not settings.IS_PRODUCTION:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += [path("__reload__/", include("django_browser_reload.urls"))]

    def _trigger_500(_: HttpRequest) -> HttpResponse:
        raise ValueError

    from ludamus.adapters.web.django.error_views import (  # pylint: disable=ungrouped-imports
        custom_404,
        custom_500,
    )

    urlpatterns += [
        path("404/", lambda r: custom_404(r, None)),
        path("500/", custom_500),
        path("500-real/", _trigger_500),
    ]

    if "debug_toolbar" in settings.INSTALLED_APPS:
        from debug_toolbar.toolbar import debug_toolbar_urls

        urlpatterns += debug_toolbar_urls()
