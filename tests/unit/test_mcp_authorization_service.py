import base64
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from ludamus.mills.mcp import (
    AUTHORIZATION_CODE_TTL_SECONDS,
    INVALID_GRANT,
    McpAuthorizationService,
)
from ludamus.pacts.mcp import (
    ClientRejection,
    MaintainerGrant,
    McpAuthorizationRejectedError,
    McpClientDTO,
    McpClientRejectedError,
    McpConsentDTO,
    McpEventChoiceDTO,
    McpGrantRejectedError,
    McpIssuedCode,
    McpPendingAuthorizationDTO,
    OrganizerGrant,
    ToolScope,
)

CLIENT_ID = "https://client.example/oauth/metadata.json"
LOOPBACK_REDIRECT = "http://127.0.0.1/callback"
SPHERE_ID = 3
USER_SLUG = "me"
CODE_LENGTH = 43
VERIFIER = "v" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .rstrip(b"=")
    .decode()
)
CLIENT = McpClientDTO(
    client_id=CLIENT_ID,
    client_name="Example Agent",
    client_host="client.example",
    redirect_uri=LOOPBACK_REDIRECT,
)


def _document(**overrides):
    return {
        "client_id": CLIENT_ID,
        "client_name": "Example Agent",
        "redirect_uris": [LOOPBACK_REDIRECT, "https://client.example/callback"],
    } | overrides


def _request(**overrides):
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": LOOPBACK_REDIRECT,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
        "scope": ToolScope.MAINTAINER,
    } | overrides


def _pending(scope=ToolScope.MAINTAINER):
    return McpPendingAuthorizationDTO(
        client=CLIENT, scope=scope, code_challenge=CHALLENGE, state="xyz"
    )


def _event(pk, *, days):
    start = datetime.now(UTC) + timedelta(days=days)
    return SimpleNamespace(
        pk=pk, name=f"Event {pk}", start_time=start, end_time=start + timedelta(hours=8)
    )


def _issued(**overrides):
    return McpIssuedCode(
        **{
            "client_id": CLIENT_ID,
            "redirect_uri": LOOPBACK_REDIRECT,
            "code_challenge": CHALLENGE,
            "grant": OrganizerGrant(user_id=7, sphere_id=3, event_id=11),
        }
        | overrides
    )


def _rejection(error):
    return (error.error, error.description, error.redirect_uri, error.state)


class FakeFetcher:
    def __init__(self, document):
        self.document = document
        self.fetched: list[str] = []

    def fetch(self, client_id):
        self.fetched.append(client_id)
        return self.document


class FakeCodes:
    def __init__(self, stored=None):
        self.stored = {} if stored is None else {"abc": (stored, None)}

    def put(self, code, issued, *, ttl_seconds):
        self.stored[code] = (issued, ttl_seconds)

    def take(self, code):
        issued, _ttl = self.stored.pop(code, (None, None))
        return issued


class FakeSpheres:
    def __init__(self, *, manager, events):
        self._managers = {(SPHERE_ID, USER_SLUG): manager}
        self._events = {SPHERE_ID: list(events)}

    def can_write_programme(self, sphere_id, slug):
        return self._managers[sphere_id, slug]

    def list_events(self, sphere_id):
        return self._events[sphere_id]


class FakeUsers:
    def __init__(self, *, superuser):
        self._users = {USER_SLUG: SimpleNamespace(is_superuser=superuser)}

    def read(self, slug):
        return self._users[slug]


class _Deps:
    def __init__(
        self, *, document=None, stored=None, superuser=True, manager=True, events=()
    ):
        self.fetcher = FakeFetcher(_document() if document is None else document)
        self.codes = FakeCodes(stored)
        self.service = McpAuthorizationService(
            fetcher=self.fetcher,
            codes=self.codes,
            spheres=FakeSpheres(manager=manager, events=events),
            users=FakeUsers(superuser=superuser),
        )

    def redeem(self, code):
        return self.service.redeem(
            code=code,
            client_id=CLIENT_ID,
            redirect_uri=LOOPBACK_REDIRECT,
            code_verifier=VERIFIER,
        )


class TestBegin:
    def test_returns_pending_authorization(self):
        deps = _Deps()

        pending = deps.service.begin(_request())

        assert pending == _pending()
        assert deps.fetcher.fetched == [CLIENT_ID]

    def test_client_that_also_supports_public_exchange_is_accepted(self):
        # ChatGPT's document: a private_key_jwt preference in the legacy
        # field, with "none" among the methods it supports.
        deps = _Deps(
            document=_document(
                token_endpoint_auth_method="private_key_jwt",
                token_endpoint_auth_methods_supported=["none", "private_key_jwt"],
            )
        )

        pending = deps.service.begin(_request())

        assert pending.client.client_id == CLIENT_ID

    def test_loopback_redirect_matches_on_any_port(self):
        deps = _Deps()

        pending = deps.service.begin(
            _request(redirect_uri="http://127.0.0.1:49152/callback")
        )

        assert pending.client.redirect_uri == "http://127.0.0.1:49152/callback"

    def test_native_app_scheme_redirect_is_accepted(self):
        # NOTE: RFC 8252 §7.1 lets a native app register a reverse-DNS scheme;
        # OAuth 2.1 §7.5.1 scopes the loopback and TLS rules to http(s). Such a
        # scheme has no host or port to judge, so it only has to be listed.
        native = "com.example.agent:/oauth/callback"
        deps = _Deps(document=_document(redirect_uris=[native]))

        pending = deps.service.begin(_request(redirect_uri=native))

        assert pending.client.redirect_uri == native

    def test_name_falls_back_to_host_and_is_capped(self):
        unnamed = _Deps(document=_document(client_name="  ")).service
        nameless = _Deps(
            document={"client_id": CLIENT_ID, "redirect_uris": [LOOPBACK_REDIRECT]}
        ).service
        long_named = _Deps(document=_document(client_name="x" * 300)).service

        assert unnamed.begin(_request()).client.client_name == "client.example"
        assert nameless.begin(_request()).client.client_name == "client.example"
        assert long_named.begin(_request()).client.client_name == "x" * 100

    @pytest.mark.parametrize(
        "client_id",
        (
            "http://client.example/metadata.json",
            "https://client.example",
            "https://client.example/",
            "https://user:pw@client.example/metadata.json",
            "https://user@client.example/metadata.json",
            "https://client.example/metadata.json#frag",
            "https://client.example/a/../metadata.json",
            "https://client.example/a/./metadata.json",
            "not a url",
        ),
    )
    def test_rejects_malformed_client_id_without_fetching(self, client_id):
        deps = _Deps()

        with pytest.raises(McpClientRejectedError) as caught:
            deps.service.begin(_request(client_id=client_id))

        assert caught.value.reason == ClientRejection.BAD_CLIENT_ID
        assert not deps.fetcher.fetched

    @pytest.mark.parametrize(
        ("document", "reason"),
        (
            (
                _document(client_id="https://other.example/m.json"),
                ClientRejection.CLIENT_ID_MISMATCH,
            ),
            (
                _document(token_endpoint_auth_method="private_key_jwt"),
                ClientRejection.CONFIDENTIAL_CLIENT,
            ),
            (
                _document(
                    token_endpoint_auth_method="private_key_jwt",
                    token_endpoint_auth_methods_supported=["private_key_jwt"],
                ),
                ClientRejection.CONFIDENTIAL_CLIENT,
            ),
            (_document(redirect_uris=[]), ClientRejection.NO_REDIRECT_URIS),
            ({"client_id": CLIENT_ID}, ClientRejection.NO_REDIRECT_URIS),
        ),
    )
    def test_rejects_unusable_document(self, document, reason):
        deps = _Deps(document=document)

        with pytest.raises(McpClientRejectedError) as caught:
            deps.service.begin(_request())

        assert caught.value.reason == reason

    @pytest.mark.parametrize(
        ("redirect_uri", "reason"),
        (
            ("https://evil.example/callback", ClientRejection.REDIRECT_NOT_LISTED),
            ("http://127.0.0.1:5000/other", ClientRejection.REDIRECT_NOT_LISTED),
            ("http://localhost/callback", ClientRejection.REDIRECT_NOT_LISTED),
            ("javascript:alert(1)", ClientRejection.BAD_REDIRECT_URI),
            ("https://client.example/callback#x", ClientRejection.BAD_REDIRECT_URI),
            ("http://client.example/callback", ClientRejection.BAD_REDIRECT_URI),
            ("https://a.example;script-src */cb", ClientRejection.BAD_REDIRECT_URI),
            ("https://client.example:99999/cb", ClientRejection.BAD_REDIRECT_URI),
            ("https:///callback", ClientRejection.BAD_REDIRECT_URI),
            ("http://[::1]:43117/callback", ClientRejection.BAD_REDIRECT_URI),
            ("", ClientRejection.BAD_REDIRECT_URI),
        ),
    )
    def test_rejects_redirect_uri(self, redirect_uri, reason):
        deps = _Deps()

        with pytest.raises(McpClientRejectedError) as caught:
            deps.service.begin(_request(redirect_uri=redirect_uri))

        assert caught.value.reason == reason

    @pytest.mark.parametrize(
        ("overrides", "error", "description"),
        (
            (
                {"response_type": "token"},
                "unsupported_response_type",
                "Only code is supported.",
            ),
            (
                {"code_challenge_method": "plain"},
                "invalid_request",
                "PKCE with S256 is required.",
            ),
            ({"code_challenge": ""}, "invalid_request", "PKCE with S256 is required."),
            ({"scope": None}, "invalid_target", "The resource must be /mcp/ here."),
        ),
    )
    def test_bad_request_is_sent_back_to_the_verified_client(
        self, overrides, error, description
    ):
        deps = _Deps()

        with pytest.raises(McpAuthorizationRejectedError) as caught:
            deps.service.begin(_request(**overrides))

        assert _rejection(caught.value) == (
            error,
            description,
            LOOPBACK_REDIRECT,
            "xyz",
        )


class TestConsent:
    def test_maintainer_needs_superuser(self):
        allowed = _Deps(superuser=True).service
        refused = _Deps(superuser=False).service

        assert allowed.consent(
            _pending(), sphere_id=SPHERE_ID, user_slug=USER_SLUG
        ) == (McpConsentDTO(may_grant=True, events=[]))
        assert refused.consent(
            _pending(), sphere_id=SPHERE_ID, user_slug=USER_SLUG
        ) == (McpConsentDTO(may_grant=False, events=[]))

    def test_organizer_lists_upcoming_soonest_first_then_past_newest_first(self):
        deps = _Deps(
            events=[
                _event(1, days=-30),
                _event(2, days=20),
                _event(3, days=5),
                _event(4, days=-10),
            ]
        )

        consent = deps.service.consent(
            _pending(ToolScope.ORGANIZER), sphere_id=SPHERE_ID, user_slug=USER_SLUG
        )

        assert consent == McpConsentDTO(
            may_grant=True,
            events=[
                McpEventChoiceDTO(pk=3, name="Event 3"),
                McpEventChoiceDTO(pk=2, name="Event 2"),
                McpEventChoiceDTO(pk=4, name="Event 4"),
                McpEventChoiceDTO(pk=1, name="Event 1"),
            ],
        )

    @freeze_time("2026-08-01 09:00:00")
    def test_organizer_lists_an_event_ending_right_now_as_upcoming(self):
        now = datetime.now(UTC)
        ending_now = SimpleNamespace(
            pk=1, name="Event 1", start_time=now - timedelta(hours=8), end_time=now
        )
        deps = _Deps(events=[_event(2, days=1), ending_now])

        consent = deps.service.consent(
            _pending(ToolScope.ORGANIZER), sphere_id=SPHERE_ID, user_slug=USER_SLUG
        )

        assert [choice.pk for choice in consent.events] == [1, 2]

    def test_organizer_without_manager_role_is_refused(self):
        deps = _Deps(manager=False, events=[_event(1, days=5)])

        consent = deps.service.consent(
            _pending(ToolScope.ORGANIZER), sphere_id=SPHERE_ID, user_slug=USER_SLUG
        )

        assert consent == McpConsentDTO(may_grant=False, events=[])


class TestApprove:
    def test_maintainer_code_is_stored(self):
        deps = _Deps()

        code = deps.service.approve(
            _pending(),
            user_id=7,
            user_slug=USER_SLUG,
            sphere_id=SPHERE_ID,
            event_id=None,
        )

        assert len(code) == CODE_LENGTH
        assert deps.codes.stored[code][1] == AUTHORIZATION_CODE_TTL_SECONDS
        assert deps.redeem(code) == MaintainerGrant(user_id=7)

    def test_organizer_code_names_the_event(self):
        deps = _Deps(events=[_event(11, days=5)])

        code = deps.service.approve(
            _pending(ToolScope.ORGANIZER),
            user_id=7,
            user_slug=USER_SLUG,
            sphere_id=SPHERE_ID,
            event_id=11,
        )

        assert deps.redeem(code) == OrganizerGrant(
            user_id=7, sphere_id=SPHERE_ID, event_id=11
        )

    @pytest.mark.parametrize("event_id", (99, None))
    def test_foreign_or_missing_event_stores_nothing(self, event_id):
        deps = _Deps(events=[_event(11, days=5)])

        with pytest.raises(McpAuthorizationRejectedError) as caught:
            deps.service.approve(
                _pending(ToolScope.ORGANIZER),
                user_id=7,
                user_slug=USER_SLUG,
                sphere_id=SPHERE_ID,
                event_id=event_id,
            )

        assert _rejection(caught.value) == (
            "invalid_request",
            "The event is not in this sphere.",
            LOOPBACK_REDIRECT,
            "xyz",
        )
        assert not deps.codes.stored

    @pytest.mark.parametrize(
        ("pending", "roles"),
        (
            (_pending(), {"superuser": False}),
            (_pending(ToolScope.ORGANIZER), {"manager": False}),
        ),
    )
    def test_user_who_may_not_grant_is_refused(self, pending, roles):
        deps = _Deps(**roles)

        with pytest.raises(McpAuthorizationRejectedError) as caught:
            deps.service.approve(
                pending,
                user_id=7,
                user_slug=USER_SLUG,
                sphere_id=SPHERE_ID,
                event_id=None,
            )

        assert _rejection(caught.value) == (
            "access_denied",
            "The user may not grant this access.",
            LOOPBACK_REDIRECT,
            "xyz",
        )
        assert not deps.codes.stored


class TestRedeem:
    def test_returns_grant(self):
        deps = _Deps(stored=_issued())

        assert deps.redeem("abc") == OrganizerGrant(user_id=7, sphere_id=3, event_id=11)

    def test_a_code_redeems_once(self):
        deps = _Deps(stored=_issued())
        deps.redeem("abc")

        with pytest.raises(McpGrantRejectedError):
            deps.redeem("abc")

    @pytest.mark.parametrize(
        ("stored", "overrides"),
        (
            (None, {}),
            (_issued(), {"client_id": "https://other.example/m.json"}),
            (_issued(), {"redirect_uri": "http://127.0.0.1:9/callback"}),
            (_issued(), {"code_verifier": "w" * 43}),
            (_issued(), {"code_verifier": "short"}),
            (_issued(), {"code_verifier": "v" * 42 + "!"}),
        ),
    )
    def test_mismatch_is_rejected(self, stored, overrides):
        deps = _Deps(stored=stored)

        with pytest.raises(McpGrantRejectedError) as caught:
            deps.service.redeem(
                **{
                    "code": "abc",
                    "client_id": CLIENT_ID,
                    "redirect_uri": LOOPBACK_REDIRECT,
                    "code_verifier": VERIFIER,
                }
                | overrides
            )

        assert str(caught.value) == INVALID_GRANT
