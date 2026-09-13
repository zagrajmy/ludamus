import pytest
from django.core.exceptions import ImproperlyConfigured

from ludamus.edges.settings import media_url_is_local, validate_media_url


class TestValidate:
    @pytest.mark.parametrize(
        "media_url",
        (
            "/media/",
            "/uploads/nested/",
            "https://media.example.com/",
            "https://media.example.com/bucket/",
            "http://localhost:8000/media/",
        ),
    )
    def test_accepts_a_servable_url(self, media_url: str):
        validate_media_url(media_url)

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
            "ftp://media.example.com/",
            "https://user:pass@media.example.com/",
            "https://media.example.com:port/",
        ),
    )
    def test_rejects_an_ambiguous_or_incomplete_url(self, media_url: str):
        with pytest.raises(ImproperlyConfigured):
            validate_media_url(media_url)


class TestIsLocal:
    @pytest.mark.parametrize("media_url", ("/media/", "/uploads/nested/"))
    def test_root_relative_paths_are_served_here(self, media_url: str):
        assert media_url_is_local(media_url)

    @pytest.mark.parametrize(
        "media_url", ("https://media.example.com/", "//media.example.com/")
    )
    def test_anything_with_a_host_is_served_elsewhere(self, media_url: str):
        assert not media_url_is_local(media_url)
