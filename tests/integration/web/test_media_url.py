import json
import os
import subprocess
import sys

import pytest

INSPECT_MEDIA_SETTINGS = """
import json

import django

django.setup()
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.urls import Resolver404, resolve
from django.views.static import serve

request_path = (
    f"{settings.MEDIA_URL}example.png"
    if settings.MEDIA_URL.startswith("/")
    else "/media/example.png"
)
try:
    serves_locally = resolve(request_path).func is serve
except Resolver404:
    serves_locally = False

print(json.dumps({
    "media_url": settings.MEDIA_URL,
    "file_url": FileSystemStorage().url("events/image.png"),
    "middleware_skips": any(
        request_path.startswith(prefix)
        for prefix in settings.MIDDLEWARE_SKIP_PREFIXES
    ),
    "serves_locally": serves_locally,
}))
"""


def inspect_media_settings(media_url: str | None) -> dict[str, str | bool]:
    environment = os.environ.copy()
    if media_url is None:
        environment.pop("MEDIA_URL", None)
    else:
        environment["MEDIA_URL"] = media_url

    completed = subprocess.run(
        [sys.executable, "-c", INSPECT_MEDIA_SETTINGS],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    return json.loads(completed.stdout)


class TestMediaUrl:
    def test_default_serves_local_media(self):
        assert inspect_media_settings(None) == {
            "media_url": "/media/",
            "file_url": "/media/events/image.png",
            "middleware_skips": True,
            "serves_locally": True,
        }

    def test_relative_override_serves_matching_local_path(self):
        assert inspect_media_settings("/uploads/") == {
            "media_url": "/uploads/",
            "file_url": "/uploads/events/image.png",
            "middleware_skips": True,
            "serves_locally": True,
        }

    def test_absolute_override_uses_remote_media_without_local_route(self):
        media_url = "https://media.example.com/"

        assert inspect_media_settings(media_url) == {
            "media_url": media_url,
            "file_url": f"{media_url}events/image.png",
            "middleware_skips": False,
            "serves_locally": False,
        }

    @pytest.mark.parametrize(
        "media_url",
        (
            "uploads/",
            "//media.example.com/",
            "https:///media/",
            "/uploads",
            "/uploads/?cache=/",
            "/",
            "/media/../uploads/",
            "/media/%2e%2e/uploads/",
            "/uploads//nested/",
            "///example.com/",
            "https://@/",
            "https://[/",
        ),
    )
    def test_rejects_ambiguous_or_incomplete_urls(self, media_url: str):
        environment = os.environ | {"MEDIA_URL": media_url}

        completed = subprocess.run(
            [sys.executable, "-c", INSPECT_MEDIA_SETTINGS],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )

        assert completed.returncode != 0
        assert "MEDIA_URL must be a root-relative path" in completed.stderr

    @pytest.mark.parametrize(
        "media_url", ("/admin/", "/panel/", "/panel/uploads/", "/mcp/", "/healthz/")
    )
    def test_rejects_media_url_colliding_with_reserved_routes(self, media_url: str):
        environment = os.environ | {"MEDIA_URL": media_url}

        completed = subprocess.run(
            [sys.executable, "-c", INSPECT_MEDIA_SETTINGS],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )

        assert completed.returncode != 0
        assert "reserved application route" in completed.stderr
