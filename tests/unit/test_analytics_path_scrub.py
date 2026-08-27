"""No URL segment that authenticates may reach the analytics project."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from secrets import token_urlsafe
from typing import TYPE_CHECKING

import pytest

from ludamus.gates.web.django.analytics_routes import build_redaction_rules, rule_for
from ludamus.links.analytics import redaction

if TYPE_CHECKING:
    from collections.abc import Iterator

NODE = shutil.which("node") or "node"
# SlugField() defaults to this, and mills.slugs caps the base at 45 + "-XXXX".
SLUG_MAX_LENGTH = 50
# models.Party.invite_token: a bare token_urlsafe is 32 bytes.
PARTY_TOKEN_LENGTH = 43
TOKEN = "Yd0Xq1mM7pQ2rS4tU6vW8xZ_aB-cD3eF5gH7iJ9kL1mN3oP5qR7sT9uV1wX3yZ5a"


@pytest.fixture(autouse=True)
def _rules() -> Iterator[None]:
    # register() pins the rules and clears the builder, so without restoring it
    # afterwards this module leaves global state behind and whether another
    # file sees any rules depends on collection order — which -n auto varies.
    redaction.register(build_redaction_rules())
    yield
    redaction.register_builder(build_redaction_rules)


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

    def test_redacts_a_link_whose_trailing_slash_was_eaten(self) -> None:
        # Matching by prefix rather than resolving is what makes this work:
        # resolve() would raise on it and the token would ship intact.
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
        assert any(source.startswith("/crowd/claim/(?<p1>") for source in sources)
        assert any(
            source.startswith("/crowd/parties/join/(?<p1>") for source in sources
        )
        assert any(source.startswith("/offer/(?<p1>") for source in sources)


class TestFloorRule:
    def test_a_long_segment_is_redacted_without_any_registered_rule(self) -> None:
        # Nothing registered: the floor alone has to hold. It is what makes
        # redaction independent of startup order, of the kwarg still being
        # spelled `token`, and of the route being a path() rather than the
        # re_path() the URLconf walk skips.
        redaction.register([])
        assert redaction.safe_path(f"/whatever/{TOKEN}/") == "/whatever/:token/"

    def test_a_share_code_is_short_enough_to_survive_the_floor(self) -> None:
        redaction.register([])
        assert redaction.safe_path("/e/ab12Cd/") == "/e/ab12Cd/"

    def test_the_party_invite_token_is_below_the_floor(self) -> None:
        # Pinned rather than aspirational: Party.invite_token is a bare
        # token_urlsafe, 43 characters, and no threshold clears both it and a
        # 50-character slug. Its route rule covers it; the floor does not. If
        # the token is ever lengthened, this test is the thing that says the
        # comment in redaction.py can be simplified.
        redaction.register([])
        token = token_urlsafe(32)
        assert len(token) == PARTY_TOKEN_LENGTH
        path = f"/crowd/parties/join/{token}/"
        assert redaction.safe_path(path) == path

    def test_a_long_slug_survives_the_floor(self) -> None:
        # SlugField defaults to 50 characters and Polish convention names use
        # them. /event/<slug>/ is the most visited page in the app, so a floor
        # that eats slugs collapses the whole page's traffic into one bucket
        # labelled as if a credential had been there.
        redaction.register([])
        slug = "ogolnopolski-konwent-fantastyki".ljust(SLUG_MAX_LENGTH, "x")
        path = f"/event/{slug}/"
        assert redaction.safe_path(path) == path

    def test_a_gravatar_digest_survives_the_floor(self) -> None:
        # sha256 is 64 characters, the same as token_urlsafe(48), and
        # components/avatar.html renders one on every authenticated page. The
        # floor tells them apart by alphabet: a digest is lower hex, a token is
        # base64url. Without that, avatars read as credentials everywhere.
        redaction.register([])
        digest = hashlib.sha256(b"someone@example.com").hexdigest()
        url = f"https://www.gravatar.com/avatar/{digest}?s=64&d=blank"
        assert len(digest) == len(token_urlsafe(48))
        assert redaction.safe_path(url) == url

    def test_a_hashed_asset_name_survives_the_floor(self) -> None:
        # The floor matches a whole segment, so a build hash keeps its
        # extension and stays readable. Vite names already run to 35 URL-safe
        # characters, so an unanchored floor would be five characters from
        # rewriting every asset URL in analytics and replay.
        redaction.register([])
        asset = "/static/vite/assets/proposal-category-settings-i_aOxcWLmNoPqRsT.js"
        assert redaction.safe_path(asset) == asset


class TestClientPatterns:
    def test_every_pattern_compiles_as_a_javascript_regexp(self) -> None:
        # Python spells a named group (?P<p1>…) and ECMAScript (?<p1>…). Shipping
        # Python's form makes `new RegExp` raise inside posthog.init, which takes
        # analytics down on every page — silently, since nothing catches it.
        for source, _replacement in redaction.client_patterns():
            assert "(?P<" not in source
            subprocess.run(
                [NODE, "-e", f"new RegExp({json.dumps(source)}, 'g')"],
                check=True,
                capture_output=True,
            )

    def test_a_kept_parameter_uses_javascript_group_syntax(self) -> None:
        rule = rule_for("event/<slug:slug>/offer/<str:token>/claim/")
        assert rule is not None
        assert rule.python == "/event/\\g<p1>/offer/:token/claim/"
        assert rule.javascript == "/event/$<p1>/offer/:token/claim/"
        assert rule.javascript_pattern.startswith("/event/(?<p1>")
