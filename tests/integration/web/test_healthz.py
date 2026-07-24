"""Integration tests for the /healthz/ endpoint."""

import math
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pytest
from django.urls import resolve

from ludamus.gates.web.django import urls as urls_module
from tests.integration.conftest import PNG_BYTES


@pytest.fixture
def _reset_healthz_cache():
    urls_module._healthz_cache.update(time=0.0, ok=True)
    yield
    urls_module._healthz_cache.update(time=0.0, ok=True)


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
        urls_module._healthz_cache.update(time=math.inf, ok=False)

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
