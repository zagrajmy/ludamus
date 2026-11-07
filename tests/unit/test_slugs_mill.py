"""Unit tests for the shared unique-slug helper (pure, IO-free)."""

from ludamus.mills.slugs import slug_base, unique_slug

_SLUG_MAX_LENGTH = 50
_COLLISION_ATTEMPTS = 4


class TestUniqueSlug:
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

    def test_gives_up_after_four_collisions_with_a_suffixed_slug(self) -> None:
        # Every candidate collides: the loop must terminate and still hand back
        # a suffixed slug rather than the bare base.
        seen: list[str] = []

        def exists(candidate: str) -> bool:
            seen.append(candidate)
            return True

        slug = unique_slug(base="taken", default="session", exists=exists)

        assert slug.startswith("taken-")
        assert len(slug) <= _SLUG_MAX_LENGTH
        assert len(seen) == _COLLISION_ATTEMPTS


class TestSlugBase:
    def test_lowercases_and_drops_non_slug_characters(self) -> None:
        assert slug_base("Auth0|User_01.AB-c") == "auth0user_01ab-c"
