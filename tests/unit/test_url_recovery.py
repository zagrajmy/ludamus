import pytest

from ludamus.mills.url_recovery import strip_trailing_junk


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        # Trailing punctuation a chat autolinker swallowed into the URL.
        ("/chronology/event/summer-con.", "/chronology/event/summer-con/"),
        ("/chronology/event/summer-con/.", "/chronology/event/summer-con/"),
        ("/chronology/event/summer-con).", "/chronology/event/summer-con/"),
        ("/chronology/event/summer-con/).", "/chronology/event/summer-con/"),
        # A trailing emoji, with or without its own path segment.
        ("/chronology/event/summer-con\U0001f600", "/chronology/event/summer-con/"),
        ("/chronology/event/summer-con/\U0001f600", "/chronology/event/summer-con/"),
        ("/chronology/event/summer-con/\U0001f600/", "/chronology/event/summer-con/"),
        # Junk on a slug also strips back to the clean slug.
        ("/chronology/event/summer-con!!!", "/chronology/event/summer-con/"),
    ),
)
def test_strips_trailing_junk(path: str, expected: str) -> None:
    assert strip_trailing_junk(path) == expected


@pytest.mark.parametrize(
    "path",
    (
        "/chronology/event/summer-con/",
        "/chronology/event/summer-con",
        "/events/",
        "/",
        "",
    ),
)
def test_clean_paths_yield_no_recovery(path: str) -> None:
    assert strip_trailing_junk(path) is None


def test_keeps_underscores_and_hyphens() -> None:
    assert strip_trailing_junk("/chronology/event/a_b-c/") is None


def test_segment_that_is_only_junk_is_dropped_to_parent() -> None:
    assert strip_trailing_junk("/chronology/event/summer-con/!!!") == (
        "/chronology/event/summer-con/"
    )
