import pytest
from django.core.exceptions import ImproperlyConfigured

from ludamus.edges.settings import media_url_is_local, validate_media_url


class TestValidate:
    @pytest.mark.parametrize(
        "media_url", ("/uploads/nested/", "https://media.example.com/bucket/")
    )
    def test_accepts_a_servable_url(self, media_url: str):
        validate_media_url(media_url)

    @pytest.mark.parametrize(
        "media_url",
        (
            "uploads/",
            "//media.example.com/",
            "/uploads",
            "/",
            "/media/../uploads/",
            "/media/%2e%2e/uploads/",
            "/uploads//nested/",
            "ftp://media.example.com/",
            "https://user:pass@media.example.com/",
        ),
    )
    def test_rejects_an_ambiguous_or_incomplete_url(self, media_url: str):
        with pytest.raises(ImproperlyConfigured):
            validate_media_url(media_url)


class TestIsLocal:
    def test_a_root_relative_path_is_served_here(self):
        assert media_url_is_local("/media/")

    def test_a_protocol_relative_url_is_served_elsewhere(self):
        assert not media_url_is_local("//media.example.com/")
