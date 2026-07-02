from django.contrib.staticfiles.storage import staticfiles_storage

from ludamus.gates.web.django.helpers import (
    PLACEHOLDER_COVER_IMAGES,
    placeholder_cover_url,
)


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
