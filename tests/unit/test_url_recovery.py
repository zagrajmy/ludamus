import pytest

from ludamus.mills.url_recovery import strip_trailing_junk


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        # Trailing punctuation a chat autolinker swallowed into the URL.
        ("/event/summer-con.", "/event/summer-con/"),
        ("/event/summer-con/.", "/event/summer-con/"),
        ("/event/summer-con).", "/event/summer-con/"),
        ("/event/summer-con/).", "/event/summer-con/"),
        # A trailing emoji, with or without its own path segment.
        ("/event/summer-con\U0001f600", "/event/summer-con/"),
        ("/event/summer-con/\U0001f600", "/event/summer-con/"),
        ("/event/summer-con/\U0001f600/", "/event/summer-con/"),
        # Junk on a slug also strips back to the clean slug.
        ("/event/summer-con!!!", "/event/summer-con/"),
    ),
)
def test_strips_trailing_junk(path: str, expected: str) -> None:
    assert strip_trailing_junk(path) == expected


@pytest.mark.parametrize(
    "path", ("/event/summer-con/", "/event/summer-con", "/events/", "/", "")
)
def test_clean_paths_yield_no_recovery(path: str) -> None:
    assert strip_trailing_junk(path) is None


def test_keeps_underscores_and_hyphens() -> None:
    assert strip_trailing_junk("/event/a_b-c/") is None


def test_segment_that_is_only_junk_is_dropped_to_parent() -> None:
    assert strip_trailing_junk("/event/summer-con/!!!") == ("/event/summer-con/")


@pytest.mark.parametrize("path", ("/.", "/!!!/", "/\U0001f600"))
def test_all_junk_path_normalises_to_root(path: str) -> None:
    assert strip_trailing_junk(path) == "/"
