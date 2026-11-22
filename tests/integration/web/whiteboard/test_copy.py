import re
from pathlib import Path

from ludamus.gates.web.django.whiteboard.copy import board_copy

_CLIENT_COPY = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "ludamus"
    / "client"
    / "src"
    / "board"
    / "copy.ts"
)


def _client_keys() -> set[str]:
    source = _CLIENT_COPY.read_text(encoding="utf-8")
    fallback = re.search(
        r"export const FALLBACK = \{(?P<body>.*?)\n\};", source, re.DOTALL
    )
    assert fallback is not None, "copy.ts no longer declares FALLBACK"
    return set(re.findall(r"^\s+(\w+):", fallback["body"], re.MULTILINE))


def test_django_translates_every_string_the_client_shows():
    # A key Django leaves out shows English to a Polish guest; a key the
    # client does not know is translated for nobody.
    client_keys = _client_keys()

    assert client_keys, "no keys parsed out of copy.ts"
    assert set(board_copy()) == client_keys


def test_placeholders_match_the_english_fallbacks():
    source = _CLIENT_COPY.read_text(encoding="utf-8")
    placeholder = re.compile(r"%\((\w+)\)s")

    for key, text in board_copy().items():
        line = re.search(
            rf"^\s+{key}:\s*\n?\s*\"(?P<text>[^\"]*)\"", source, re.MULTILINE
        )
        assert line is not None, key
        assert set(placeholder.findall(text)) == set(
            placeholder.findall(line["text"])
        ), key
