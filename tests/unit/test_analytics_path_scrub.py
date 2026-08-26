"""The reported path must never carry a claim or invite token."""

from __future__ import annotations

import pytest

from ludamus.links.analytics.identity import safe_path

TOKEN = "Yd0Xq1mM7pQ2rS4tU6vW8xZ_aB-cD3eF5gH7iJ9kL1mN3oP5qR7sT9uV1wX3yZ5a"


class TestSafePath:
    @pytest.mark.parametrize(
        ("path", "expected"),
        (
            (f"/crowd/claim/{TOKEN}/", "/crowd/claim/:token/"),
            (f"/crowd/parties/join/{TOKEN}/", "/crowd/parties/join/:token/"),
            (f"/crowd/claim/{TOKEN}", "/crowd/claim/:token"),
        ),
    )
    def test_token_is_replaced(self, path: str, expected: str) -> None:
        assert safe_path(path) == expected
        assert TOKEN not in safe_path(path)

    @pytest.mark.parametrize(
        "path",
        ("/events/", "/crowd/profile/", "/event/con-2026/facilitators/jill-hill/"),
    )
    def test_other_paths_are_untouched(self, path: str) -> None:
        assert safe_path(path) == path
