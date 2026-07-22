"""Unit tests for the panel's unique-slug helper (pure, IO-free)."""

from ludamus.gates.web.django.chronology.panel.views.base import make_unique_slug

_SLUG_MAX_LENGTH = 50


class TestMakeUniqueSlug:
    def test_returns_base_slug_when_available(self) -> None:
        slug = make_unique_slug("Hello World", "session", lambda _s: False)

        assert slug == "hello-world"

    def test_falls_back_to_default_for_empty_slug(self) -> None:
        slug = make_unique_slug("!!!", "session", lambda _s: False)

        assert slug == "session"

    def test_caps_long_name_to_column_length(self) -> None:
        # A 60-char title slugifies past varchar(50); the base must be trimmed so
        # the INSERT can't overflow on Postgres (SQLite silently ignores it).
        slug = make_unique_slug("a" * 60, "session", lambda _s: False)

        assert len(slug) <= _SLUG_MAX_LENGTH

    def test_disambiguated_slug_still_fits_column(self) -> None:
        # The collision suffix ("-" + token) must fit alongside the base: a long
        # title that collides once was the "second create 500s" production bug.
        seen: list[str] = []

        def exists(candidate: str) -> bool:
            seen.append(candidate)
            return len(seen) == 1  # only the first candidate collides

        slug = make_unique_slug("a" * 60, "session", exists)

        assert len(slug) <= _SLUG_MAX_LENGTH
        assert slug != seen[0]  # a suffix was appended after the collision
