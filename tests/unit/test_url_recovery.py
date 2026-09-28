import pytest

from ludamus.mills.url_recovery import strip_trailing_junk


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        # Trailing punctuation a chat autolinker swallowed into the URL.
        ("/event/summer-con/).", "/event/summer-con/"),
        # A trailing emoji in its own path segment.
        ("/event/summer-con/\U0001f600/", "/event/summer-con/"),
        # Junk on a slug also strips back to the clean slug.
        ("/event/summer-con!!!", "/event/summer-con/"),
        # A segment that is only junk drops to its parent.
        ("/event/summer-con/!!!", "/event/summer-con/"),
        ("/!!!/", "/"),
    ),
)
def test_strips_trailing_junk(path: str, expected: str) -> None:
    assert strip_trailing_junk(path) == expected


@pytest.mark.parametrize("path", ("/event/summer-con", "/event/a_b-c/", ""))
def test_clean_paths_yield_no_recovery(path: str) -> None:
    assert strip_trailing_junk(path) is None
