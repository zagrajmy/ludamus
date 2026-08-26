"""No URL segment that authenticates may reach the analytics project."""

from __future__ import annotations

import pytest

from ludamus.gates.web.django.analytics_routes import register_redaction_rules
from ludamus.links.analytics import redaction

TOKEN = "Yd0Xq1mM7pQ2rS4tU6vW8xZ_aB-cD3eF5gH7iJ9kL1mN3oP5qR7sT9uV1wX3yZ5a"


@pytest.fixture(autouse=True)
def _rules() -> None:
    register_redaction_rules()


class TestSafePath:
    @pytest.mark.parametrize(
        ("path", "expected"),
        (
            (f"/crowd/claim/{TOKEN}/", "/crowd/claim/:token/"),
            (f"/crowd/parties/join/{TOKEN}/", "/crowd/parties/join/:token/"),
            (f"/offer/{TOKEN}/claim/", "/offer/:token/claim/"),
            (f"/offer/{TOKEN}/decline/", "/offer/:token/decline/"),
        ),
    )
    def test_bearer_token_is_replaced(self, path: str, expected: str) -> None:
        assert redaction.safe_path(path) == expected

    def test_fails_closed_when_the_path_does_not_resolve(self) -> None:
        # A chat client that eats the trailing slash still produces a link that
        # carries the whole credential; resolving would raise here.
        assert TOKEN not in redaction.safe_path(f"/crowd/claim/{TOKEN}")

    @pytest.mark.parametrize(
        "path",
        (
            "/events/",
            "/crowd/profile/",
            "/event/con-2026/",
            # share_code is made to be pasted and QR-encoded, so it stays
            # readable and the notice board keeps per-encounter analytics.
            "/e/ab12Cd/",
        ),
    )
    def test_paths_without_secrets_are_untouched(self, path: str) -> None:
        assert redaction.safe_path(path) == path

    def test_rules_come_from_the_urlconf(self) -> None:
        # The point of deriving them: a route added with a token parameter is
        # covered without anyone editing a list. Guard the derivation, and name
        # the routes it must have found rather than counting them.
        sources = {source for source, _replacement in redaction.client_patterns()}
        assert "/crowd/claim/([^/?#]+)" in sources
        assert "/crowd/parties/join/([^/?#]+)" in sources
        assert "/offer/([^/?#]+)" in sources


class TestClientPatterns:
    def test_replacements_use_javascript_group_syntax(self) -> None:
        for _source, replacement in redaction.client_patterns():
            assert "\\" not in replacement
