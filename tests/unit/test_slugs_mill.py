"""Unit tests for the shared unique-slug helper (pure, IO-free)."""

from ludamus.mills.slugs import unique_slug

_SLUG_MAX_LENGTH = 50


class TestUniqueSlug:
    def test_returns_base_slug_when_available(self) -> None:
        slug = unique_slug(
            base="hello-world", default="session", exists=lambda _s: False
        )

        assert slug == "hello-world"

    def test_falls_back_to_default_for_empty_base(self) -> None:
        slug = unique_slug(base="", default="session", exists=lambda _s: False)

        assert slug == "session"

    def test_caps_long_base_to_column_length(self) -> None:
        # A 60-char base is past varchar(50); it must be trimmed so the INSERT
        # can't overflow on Postgres (SQLite silently ignores it).
        slug = unique_slug(base="a" * 60, default="session", exists=lambda _s: False)

        assert len(slug) <= _SLUG_MAX_LENGTH

    def test_caps_long_default_fallback(self) -> None:
        # An empty base falls back to the default, which must also be capped so
        # an over-long default can't overflow the column.
        slug = unique_slug(base="", default="d" * 60, exists=lambda _s: False)

        assert len(slug) <= _SLUG_MAX_LENGTH

    def test_disambiguated_slug_still_fits_column(self) -> None:
        # The collision suffix ("-" + token) must fit alongside the base: a long
        # title that collides once was the "second create 500s" production bug.
        seen: list[str] = []

        def exists(candidate: str) -> bool:
            seen.append(candidate)
            return len(seen) == 1  # only the first candidate collides

        slug = unique_slug(base="a" * 60, default="session", exists=exists)

        assert len(slug) <= _SLUG_MAX_LENGTH
        assert slug != seen[0]  # a suffix was appended after the collision
