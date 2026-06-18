"""Integration tests for the /healthz/ endpoint."""

import math
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pytest
from django.urls import resolve

from ludamus.gates.web.django import urls as urls_module

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def _reset_healthz_cache():
    urls_module._healthz_cache.update(time=0.0, ok=True)  # noqa: SLF001
    yield
    urls_module._healthz_cache.update(time=0.0, ok=True)  # noqa: SLF001


class TestHealthz:
    pytestmark = pytest.mark.usefixtures("_reset_healthz_cache")
    def test_returns_ok_on_fresh_request(self, client):
        response = client.get("/healthz/")

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"status": "ok"}

    def test_returns_cached_ok_within_window(self, client):
        client.get("/healthz/")

        with patch.object(urls_module.connection, "cursor") as cursor_mock:
            response = client.get("/healthz/")

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"status": "ok"}
        cursor_mock.assert_not_called()

    def test_returns_cached_error_within_window(self, client):
        urls_module._healthz_cache.update(time=math.inf, ok=False)  # noqa: SLF001

        response = client.get("/healthz/")

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.json() == {"status": "error"}

    def test_returns_error_on_db_failure(self, client):
        with patch.object(urls_module.connection, "cursor", side_effect=RuntimeError):
            response = client.get("/healthz/")

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.json() == {"status": "error"}


class TestMediaUrls:
    def test_serves_uploaded_file_under_media_prefix(self, client):
        rel = "sessions/test-cover.png"
        media_root = Path(resolve(f"/media/{rel}").kwargs["document_root"])
        target = media_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG_BYTES)

        response = client.get(f"/media/{rel}")

        assert response.status_code == HTTPStatus.OK
        assert b"".join(response.streaming_content) == PNG_BYTES
