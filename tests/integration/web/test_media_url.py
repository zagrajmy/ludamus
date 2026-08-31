import json
import os
import subprocess
import sys

import pytest

from ludamus.gates.web.django.checks import MEDIA_URL_SHADOWED

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


RUN_URL_CHECKS = """
import django

django.setup()

from django.core.management import call_command

call_command("check", "--tag", "urls")
"""


def run_url_checks(media_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", RUN_URL_CHECKS],
        check=False,
        capture_output=True,
        env=os.environ | {"MEDIA_URL": media_url},
        text=True,
    )


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

    def test_settings_refuse_to_boot_on_a_url_the_app_cannot_serve(self):
        # The rule itself is covered in tests/unit/test_media_url.py; this is
        # about settings enforcing it at import time.
        environment = os.environ | {"MEDIA_URL": "/uploads"}

        completed = subprocess.run(
            [sys.executable, "-c", INSPECT_MEDIA_SETTINGS],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )

        assert completed.returncode != 0
        assert "MEDIA_URL must be a root-relative path" in completed.stderr

    @pytest.mark.parametrize("media_url", ("/chronology/", "/admin/"))
    def test_system_check_reports_media_url_a_route_answers_first(self, media_url: str):
        completed = run_url_checks(media_url)

        assert completed.returncode != 0
        assert MEDIA_URL_SHADOWED in completed.stdout + completed.stderr

    @pytest.mark.parametrize("media_url", ("/media/", "/uploads/"))
    def test_system_check_passes_for_media_url_the_media_view_answers(
        self, media_url: str
    ):
        completed = run_url_checks(media_url)

        assert completed.returncode == 0, completed.stdout + completed.stderr
