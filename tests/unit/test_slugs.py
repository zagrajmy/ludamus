import pytest

from ludamus.mills.slugs import unique_slug as unique_slug_from_base
from ludamus.pacts.slugs import (
    SLUG_MAX_LENGTH,
    SlugCollisionError,
    slugify,
    unique_slug,
)

SUFFIX_LENGTH = 4  # token_urlsafe(3) as base64
ATTEMPTS = 8


class TestUniqueSlug:
    def test_a_free_title_slug_is_taken_as_is(self):
        assert unique_slug("Łódź Games", exists=lambda _s: False, fallback="x") == (
            "lodz-games"
        )

    def test_appends_suffix_until_free(self):
        taken = {"my-talk"}

        slug = unique_slug("My Talk", exists=lambda s: s in taken, fallback="x")

        assert slug.startswith("my-talk-")
        assert len(slug) == len("my-talk-") + SUFFIX_LENGTH

    def test_raises_after_eight_taken_candidates(self):
        tried: list[str] = []

        def taken(slug: str) -> bool:
            tried.append(slug)
            return True

        with pytest.raises(SlugCollisionError) as exc_info:
            unique_slug("My Talk", exists=taken, fallback="x")

        assert len(tried) == ATTEMPTS
        assert exc_info.value.base_slug == "my-talk"
        assert str(exc_info.value) == "Could not generate a unique slug for 'my-talk'."

    def test_a_long_title_that_collides_still_fits_the_column(self):
        # The "second create 500s on Postgres" bug: base plus suffix overflowed
        # varchar(50).
        taken = {slugify("x" * 80)}

        slug = unique_slug("x" * 80, exists=lambda s: s in taken, fallback="x")

        assert len(slug) == SLUG_MAX_LENGTH
        assert slug not in taken

    def test_strips_the_dash_the_cut_leaves_before_the_suffix(self):
        title = f"{'a' * 45} bbbb"

        slug = unique_slug(title, exists=lambda s: s == slugify(title), fallback="x")

        assert slug.startswith(f"{'a' * 45}-")
        assert "--" not in slug

    def test_an_unsluggable_title_falls_back(self):
        assert unique_slug("!!!", exists=lambda _s: False, fallback="event") == "event"

    def test_an_over_long_fallback_is_capped(self):
        slug = unique_slug("", exists=lambda _s: False, fallback="d" * 60)

        assert len(slug) == SLUG_MAX_LENGTH


class TestUniqueSlugFromBase:
    def test_follows_the_same_rule_as_unique_slug(self):
        assert unique_slug_from_base(
            base="", default="session", exists=lambda _s: False
        ) == ("session")


class TestSlugify:
    def test_truncation_drops_trailing_dash(self):
        # 49 chars then a space+word so the cut lands on a separator
        assert not slugify(f"{'a' * 49} bb").endswith("-")

    def test_caps_at_the_slug_column_width_by_default(self):
        assert len(slugify("x" * 80)) == SLUG_MAX_LENGTH

    def test_strips_a_leading_dash_before_capping(self):
        assert slugify(f"-{'a' * SLUG_MAX_LENGTH}") == "a" * SLUG_MAX_LENGTH

    def test_honours_a_custom_max_length(self):
        assert slugify("x" * 80, max_length=10) == "x" * 10
