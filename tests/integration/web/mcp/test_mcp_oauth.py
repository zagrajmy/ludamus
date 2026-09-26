import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import quote, urlencode

import pytest
from django.core.cache import cache
from freezegun import freeze_time

from ludamus.gates.web.django.mcp.tokens import mint_organizer_token, mint_token
from ludamus.pacts.mcp import McpClientDTO
from tests.integration.cimd import install
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.utils import (
    FormFieldsMatcher,
    assert_login_required,
    assert_response,
)

AUTHORIZE_URL = "/mcp/oauth/authorize/"
TOKEN_URL = "/mcp/oauth/token/"
CLIENT_ID = "https://client.example/oauth/metadata.json"
REDIRECT_URI = "http://127.0.0.1:43117/callback"
MAINTAINER_RESOURCE = "http://testserver/mcp/"
ORGANIZER_RESOURCE = "http://testserver/mcp/organizer/"
# secrets.token_urlsafe mints both the consent page's pending id and the code.
TOKEN = "fixed-random-token"
VERIFIER = "correct-horse-battery-staple-" + "v" * 20
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .rstrip(b"=")
    .decode()
)
CLIENT = McpClientDTO(
    client_id=CLIENT_ID,
    client_name="Example Agent",
    client_host="client.example",
    redirect_uri=REDIRECT_URI,
)
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
PONG = {"jsonrpc": "2.0", "id": 1, "result": {}}
NO_STORE = {"Cache-Control": "no-store"}
INVALID_GRANT = {
    "error": "invalid_grant",
    "error_description": (
        "The authorization code is invalid or was issued for another request."
    ),
}
EXPIRED = "This connection request expired. Start again from your client."

pytestmark = pytest.mark.usefixtures("client_metadata", "fixed_tokens")


@pytest.fixture(name="client_metadata")
def client_metadata_fixture(monkeypatch):
    server = install(monkeypatch)
    server.serve(
        "/oauth/metadata.json",
        document={
            "client_id": CLIENT_ID,
            "client_name": "Example Agent",
            "redirect_uris": ["http://127.0.0.1/callback"],
        },
    )
    return server


@pytest.fixture(name="fixed_tokens")
def fixed_tokens_fixture(monkeypatch):
    monkeypatch.setattr("secrets.token_urlsafe", lambda _n=None: TOKEN)
    # Every test issues the same code, so an unredeemed one would leak into
    # the next test through the process-wide locmem cache.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(name="superuser")
def superuser_fixture():
    return UserFactory(username="maintainer", is_superuser=True)


@pytest.fixture(name="superuser_client")
def superuser_client_fixture(client, superuser):
    client.force_login(superuser)
    return client


def _params(resource=MAINTAINER_RESOURCE, **overrides):
    return {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": resource,
    } | overrides


def _consent_context(*, scope="maintainer", **overrides):
    return {
        "client_error": None,
        "client": CLIENT,
        "scope": scope,
        "may_grant": True,
        "wants_event": scope == "organizer",
        "form": None,
        "can_approve": True,
        "pending": TOKEN,
        "token_max_age_days": 30,
    } | overrides


def _decide(client, decision, resource=MAINTAINER_RESOURCE, **extra):
    client.get(AUTHORIZE_URL, _params(resource=resource))
    return client.post(AUTHORIZE_URL, {"pending": TOKEN, "decision": decision} | extra)


def _client_redirect(**params):
    query = params | {"iss": "http://testserver", "state": "xyz"}
    return f"{REDIRECT_URI}?{urlencode(query)}"


def _exchange(client, **overrides):
    return client.post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": TOKEN,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
        }
        | overrides,
    )


def _token_body(token):
    return {"access_token": token, "token_type": "Bearer", "expires_in": 2592000}


def _post_mcp(client, url, token):
    return client.post(
        url,
        data=json.dumps(PING),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


class TestDiscovery:
    def test_authorization_server_metadata(self, client):
        response = client.get("/.well-known/oauth-authorization-server")

        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "issuer": "http://testserver",
                "authorization_endpoint": "http://testserver/mcp/oauth/authorize/",
                "token_endpoint": "http://testserver/mcp/oauth/token/",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "client_id_metadata_document_supported": True,
                "authorization_response_iss_parameter_supported": True,
            },
        )

    @pytest.mark.parametrize(
        ("path", "resource", "scope"),
        (
            ("mcp/", MAINTAINER_RESOURCE, "maintainer"),
            ("mcp/organizer/", ORGANIZER_RESOURCE, "organizer"),
        ),
    )
    def test_protected_resource_metadata(self, client, path, resource, scope):
        response = client.get(f"/.well-known/oauth-protected-resource/{path}")

        assert_response(
            response,
            HTTPStatus.OK,
            json={
                "resource": resource,
                "authorization_servers": ["http://testserver"],
                "bearer_methods_supported": ["header"],
                "resource_name": f"Zagrajmy MCP ({scope})",
            },
        )

    @pytest.mark.parametrize(
        ("url", "scope"), (("/mcp/", "maintainer"), ("/mcp/organizer/", "organizer"))
    )
    def test_unauthorized_endpoint_points_at_metadata(self, client, url, scope):
        response = client.post(
            url, data=json.dumps(PING), content_type="application/json"
        )

        assert_response(
            response,
            HTTPStatus.UNAUTHORIZED,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="http://testserver/.well-known/'
                    f'oauth-protected-resource{url}"'
                )
            },
            json={"error": f"A valid {scope} Bearer token is required."},
        )


class TestAuthorizeRequest:
    def test_login_required(self, client, client_metadata):
        path = f"{AUTHORIZE_URL}?{urlencode(_params())}"

        response = client.get(path)

        assert_login_required(response, quote(path, safe="/"))
        assert not client_metadata.fetches

    @pytest.mark.parametrize(
        ("overrides", "client_error"),
        (
            (
                {"redirect_uri": "https://evil.example/callback"},
                (
                    "The client asked to return to an address its metadata "
                    "doesn't list."
                ),
            ),
            (
                {"client_id": "client-123"},
                "The client did not identify itself with a metadata document URL.",
            ),
        ),
    )
    def test_unverified_client_gets_error_page_not_redirect(
        self, superuser_client, overrides, client_error
    ):
        response = superuser_client.get(AUTHORIZE_URL, _params(**overrides))

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={"client_error": client_error},
        )

    def test_fetch_failure_hides_the_status(self, superuser_client, client_metadata):
        client_metadata.serve("/oauth/metadata.json", status=500, body=b"")

        response = superuser_client.get(AUTHORIZE_URL, _params())

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={
                "client_error": "The client's metadata document could not be fetched."
            },
        )

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
            (
                {"resource": "https://elsewhere.example/mcp/"},
                "invalid_target",
                "The resource must be /mcp/ here.",
            ),
        ),
    )
    def test_invalid_request_redirects_back_with_error(
        self, superuser_client, overrides, error, description
    ):
        response = superuser_client.get(AUTHORIZE_URL, _params(**overrides))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_client_redirect(error=error, error_description=description),
        )

    def test_unknown_pending_request_expired(self, superuser_client):
        response = superuser_client.post(
            AUTHORIZE_URL, {"pending": "gone", "decision": "approve"}
        )

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={"client_error": EXPIRED},
        )


class TestMaintainerConsent:
    def test_superuser_sees_consent(self, superuser_client):
        response = superuser_client.get(AUTHORIZE_URL, _params())

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(),
        )

    def test_resource_without_trailing_slash_is_accepted(self, superuser_client):
        response = superuser_client.get(
            AUTHORIZE_URL, _params(resource="http://testserver/mcp")
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(),
        )

    def test_non_superuser_cannot_grant(self, authenticated_client):
        response = authenticated_client.get(AUTHORIZE_URL, _params())

        assert_response(
            response,
            HTTPStatus.FORBIDDEN,
            template_name="mcp/authorize.html",
            context_data=_consent_context(may_grant=False, can_approve=False),
        )

    def test_non_superuser_approve_issues_no_code(self, authenticated_client, client):
        response = _decide(authenticated_client, "approve")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_client_redirect(
                error="access_denied",
                error_description="The user may not grant this access.",
            ),
        )
        assert_response(
            _exchange(client),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json=INVALID_GRANT,
        )

    def test_deny_redirects_with_access_denied(self, superuser_client):
        response = _decide(superuser_client, "deny")

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_client_redirect(
                error="access_denied", error_description="The user denied access."
            ),
        )

    def test_stale_tab_leaves_the_current_request_alone(
        self, superuser_client, monkeypatch
    ):
        superuser_client.get(AUTHORIZE_URL, _params())
        monkeypatch.setattr("secrets.token_urlsafe", lambda _n=None: "newer-tab")
        superuser_client.get(AUTHORIZE_URL, _params())

        stale = superuser_client.post(
            AUTHORIZE_URL, {"pending": TOKEN, "decision": "approve"}
        )
        current = superuser_client.post(
            AUTHORIZE_URL, {"pending": "newer-tab", "decision": "deny"}
        )

        assert_response(
            stale,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={"client_error": EXPIRED},
        )
        assert_response(
            current,
            HTTPStatus.FOUND,
            url=_client_redirect(
                error="access_denied", error_description="The user denied access."
            ),
        )

    def test_decision_does_not_refetch_client_metadata(
        self, superuser_client, client_metadata
    ):
        _decide(superuser_client, "approve")

        assert len(client_metadata.fetches) == 1

    @freeze_time("2026-09-25 12:00:00")
    def test_full_flow_yields_single_use_maintainer_token(
        self, superuser_client, client, superuser
    ):
        approve = _decide(superuser_client, "approve")
        replay = superuser_client.post(
            AUTHORIZE_URL, {"pending": TOKEN, "decision": "approve"}
        )
        superuser_client.logout()
        token = mint_token(superuser.pk)

        assert_response(approve, HTTPStatus.FOUND, url=_client_redirect(code=TOKEN))
        assert_response(
            replay,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={"client_error": EXPIRED},
        )
        assert_response(
            _exchange(client), HTTPStatus.OK, headers=NO_STORE, json=_token_body(token)
        )
        assert_response(
            _exchange(client),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json=INVALID_GRANT,
        )
        assert_response(_post_mcp(client, "/mcp/", token), HTTPStatus.OK, json=PONG)
        assert_response(
            _post_mcp(client, "/mcp/organizer/", token),
            HTTPStatus.UNAUTHORIZED,
            json={"error": "A valid organizer Bearer token is required."},
        )


@pytest.mark.usefixtures("client_metadata", "fixed_tokens", "issued_code")
class TestTokenExchange:
    @pytest.fixture(name="issued_code")
    def issued_code_fixture(self, superuser_client):
        _decide(superuser_client, "approve")
        superuser_client.logout()

    @pytest.mark.parametrize(
        "overrides",
        (
            {"code_verifier": "w" * 43},
            {"client_id": "https://other.example/metadata.json"},
            {"redirect_uri": "http://127.0.0.1:1/callback"},
        ),
    )
    def test_mismatch_is_invalid_grant(self, client, overrides):
        assert_response(
            _exchange(client, **overrides),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json=INVALID_GRANT,
        )

    def test_unsupported_grant_type(self, client):
        response = client.post(TOKEN_URL, {"grant_type": "refresh_token"})

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json={
                "error": "unsupported_grant_type",
                "error_description": "Only authorization_code is supported.",
            },
        )


class TestOrganizerConsent:
    @pytest.fixture(name="manager")
    def manager_fixture(self, sphere):
        manager = UserFactory(username="orgmanager")
        sphere.managers.add(manager)
        return manager

    @pytest.fixture(name="manager_client")
    def manager_client_fixture(self, client, manager):
        client.force_login(manager)
        return client

    def test_manager_picks_event_upcoming_first(self, manager_client, sphere):
        now = datetime.now(UTC)
        past = EventFactory(
            sphere=sphere,
            name="Past",
            start_time=now - timedelta(days=30),
            end_time=now - timedelta(days=29),
        )
        upcoming = EventFactory(
            sphere=sphere,
            name="Upcoming",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=6),
        )

        response = manager_client.get(
            AUTHORIZE_URL, _params(resource=ORGANIZER_RESOURCE)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(
                scope="organizer",
                form=FormFieldsMatcher(
                    event={"choices": [(upcoming.pk, "Upcoming"), (past.pk, "Past")]}
                ),
            ),
        )

    def test_forged_approve_without_events_redirects_with_error(
        self, manager_client, client
    ):
        response = _decide(manager_client, "approve", resource=ORGANIZER_RESOURCE)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_client_redirect(
                error="invalid_request",
                error_description="The event is not in this sphere.",
            ),
        )
        assert_response(
            _exchange(client),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json=INVALID_GRANT,
        )

    def test_sphere_without_events_cannot_approve(self, manager_client):
        response = manager_client.get(
            AUTHORIZE_URL, _params(resource=ORGANIZER_RESOURCE)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(scope="organizer", can_approve=False),
        )

    @pytest.mark.usefixtures("event")
    def test_non_manager_cannot_grant(self, authenticated_client):
        response = authenticated_client.get(
            AUTHORIZE_URL, _params(resource=ORGANIZER_RESOURCE)
        )

        assert_response(
            response,
            HTTPStatus.FORBIDDEN,
            template_name="mcp/authorize.html",
            context_data=_consent_context(
                scope="organizer", may_grant=False, wants_event=False, can_approve=False
            ),
        )

    def test_foreign_event_is_refused_without_code(self, manager_client, client, event):
        foreign = EventFactory(sphere=SphereFactory())

        response = _decide(
            manager_client, "approve", resource=ORGANIZER_RESOURCE, event=foreign.pk
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(
                scope="organizer",
                form=FormFieldsMatcher(event={"choices": [(event.pk, event.name)]}),
            ),
        )
        assert_response(
            _exchange(client),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json=INVALID_GRANT,
        )

    @freeze_time("2026-09-25 12:00:00")
    def test_full_flow_yields_event_scoped_token(
        self, manager_client, client, manager, sphere, event
    ):
        approve = _decide(
            manager_client, "approve", resource=ORGANIZER_RESOURCE, event=event.pk
        )
        manager_client.logout()
        token = mint_organizer_token(
            user_id=manager.pk, sphere_id=sphere.pk, event_id=event.pk
        )

        assert_response(approve, HTTPStatus.FOUND, url=_client_redirect(code=TOKEN))
        assert_response(
            _exchange(client), HTTPStatus.OK, headers=NO_STORE, json=_token_body(token)
        )
        assert_response(
            _post_mcp(client, "/mcp/organizer/", token), HTTPStatus.OK, json=PONG
        )
        assert_response(
            _post_mcp(client, "/mcp/", token),
            HTTPStatus.UNAUTHORIZED,
            json={"error": "A valid maintainer Bearer token is required."},
        )
