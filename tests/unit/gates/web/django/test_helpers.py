from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import RequestFactory

from ludamus.gates.web.django.helpers import (
    PLACEHOLDER_COVER_IMAGES,
    get_client_ip,
    placeholder_cover_url,
)


class TestGetClientIp:
    def test_cloudflare_header_wins_over_forwarded_for(self) -> None:
        request = RequestFactory().get(
            "/",
            HTTP_CF_CONNECTING_IP="203.0.113.50",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1",
            REMOTE_ADDR="10.0.0.2",
        )

        assert get_client_ip(request) == "203.0.113.50"

    def test_rightmost_forwarded_for_without_cloudflare(self) -> None:
        request = RequestFactory().get(
            "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1", REMOTE_ADDR="10.0.0.2"
        )

        assert get_client_ip(request) == "10.0.0.1"

    def test_remote_addr_without_proxy_headers(self) -> None:
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.2")

        assert get_client_ip(request) == "10.0.0.2"


class TestPlaceholderCoverUrl:
    def test_resolves_static_url_for_key(self) -> None:
        assert placeholder_cover_url(0) == staticfiles_storage.url(
            "placeholder-images/01.webp"
        )

    def test_is_deterministic(self) -> None:
        assert placeholder_cover_url(7) == placeholder_cover_url(7)

    def test_cycles_by_modulo(self) -> None:
        count = len(PLACEHOLDER_COVER_IMAGES)

        assert placeholder_cover_url(3) == placeholder_cover_url(3 + count)
