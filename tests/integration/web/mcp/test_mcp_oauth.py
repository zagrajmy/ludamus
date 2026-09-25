import base64
import hashlib
import json
import socket
from http import HTTPStatus
from unittest.mock import ANY
from urllib.parse import quote, urlencode

import pytest
import responses
from django.core.cache import cache
from freezegun import freeze_time

from ludamus.gates.web.django.mcp.tokens import mint_organizer_token, mint_token
from ludamus.pacts.mcp import McpClientDTO
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_login_required, assert_response

AUTHORIZE_URL = "/mcp/oauth/authorize/"
TOKEN_URL = "/mcp/oauth/token/"
CLIENT_ID = "https://client.example/oauth/metadata.json"
REDIRECT_URI = "http://127.0.0.1:43117/callback"
MAINTAINER_RESOURCE = "http://testserver/mcp/"
ORGANIZER_RESOURCE = "http://testserver/mcp/organizer/"
CODE = "fixed-authorization-code"
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
SPENT_CODE = {
    "error": "invalid_grant",
    "error_description": "The authorization code is invalid, expired, or already used.",
}

pytestmark = pytest.mark.usefixtures("client_metadata", "fixed_code")


@pytest.fixture(name="client_metadata")
def client_metadata_fixture(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda _host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(
            CLIENT_ID,
            json={
                "client_id": CLIENT_ID,
                "client_name": "Example Agent",
                "redirect_uris": ["http://127.0.0.1/callback"],
            },
        )
        yield rsps


@pytest.fixture(name="fixed_code")
def fixed_code_fixture(monkeypatch):
    monkeypatch.setattr("ludamus.mills.mcp.secrets.token_urlsafe", lambda _n: CODE)
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


def _consent_context(*, resource=MAINTAINER_RESOURCE, **overrides):
    scope = "organizer" if resource == ORGANIZER_RESOURCE else "maintainer"
    return {
        "client_error": None,
        "client": CLIENT,
        "scope": scope,
        "may_grant": True,
        "wants_event": scope == "organizer",
        "form": None,
        "can_approve": True,
        "params": _params(resource=resource),
        "token_max_age_days": 30,
    } | overrides


def _client_redirect(**params):
    return f"{REDIRECT_URI}?{urlencode(params | {'state': 'xyz'})}"


def _code_redirect():
    return _client_redirect(code=CODE, iss="http://testserver")


def _error_redirect(error, description):
    return _client_redirect(
        error=error, error_description=description, iss="http://testserver"
    )


def _exchange(client, **overrides):
    return client.post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": CODE,
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
    def test_login_required(self, client):
        path = f"{AUTHORIZE_URL}?{urlencode(_params())}"

        response = client.get(path)

        assert_login_required(response, quote(path, safe="/"))

    @pytest.mark.parametrize(
        ("overrides", "client_error"),
        (
            (
                {"redirect_uri": "https://evil.example/callback"},
                "The redirect_uri is not listed in the client metadata document.",
            ),
            (
                {"client_id": "client-123"},
                "The client_id must be an https URL of a client metadata document.",
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

    def test_metadata_fetch_failure_gets_error_page(
        self, superuser_client, client_metadata
    ):
        client_metadata.replace(responses.GET, CLIENT_ID, status=500)

        response = superuser_client.get(AUTHORIZE_URL, _params())

        assert_response(
            response,
            HTTPStatus.BAD_REQUEST,
            template_name="mcp/authorize.html",
            context_data={
                "client_error": "The client metadata document answered with HTTP 500."
            },
        )

    @pytest.mark.parametrize(
        ("overrides", "error", "description"),
        (
            (
                {"response_type": "token"},
                "unsupported_response_type",
                "Only response_type=code is supported.",
            ),
            (
                {"code_challenge_method": "plain"},
                "invalid_request",
                "PKCE with code_challenge_method=S256 is required.",
            ),
            (
                {"code_challenge": ""},
                "invalid_request",
                "PKCE with code_challenge_method=S256 is required.",
            ),
            (
                {"resource": "https://elsewhere.example/mcp/"},
                "invalid_target",
                "The resource must be this site's /mcp/ endpoint.",
            ),
        ),
    )
    def test_invalid_request_redirects_back_with_error(
        self, superuser_client, overrides, error, description
    ):
        response = superuser_client.get(AUTHORIZE_URL, _params(**overrides))

        assert_response(
            response, HTTPStatus.FOUND, url=_error_redirect(error, description)
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
        response = authenticated_client.post(
            AUTHORIZE_URL, _params() | {"decision": "approve"}
        )

        assert_response(
            response,
            HTTPStatus.FORBIDDEN,
            template_name="mcp/authorize.html",
            context_data=_consent_context(may_grant=False, can_approve=False),
        )
        assert_response(
            _exchange(client), HTTPStatus.BAD_REQUEST, headers=NO_STORE, json=SPENT_CODE
        )

    def test_deny_redirects_with_access_denied(self, superuser_client):
        response = superuser_client.post(
            AUTHORIZE_URL, _params() | {"decision": "deny"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_error_redirect("access_denied", "The user denied access."),
        )

    @freeze_time("2026-09-25 12:00:00")
    def test_full_flow_yields_single_use_maintainer_token(
        self, superuser_client, client, superuser
    ):
        approve = superuser_client.post(
            AUTHORIZE_URL, _params() | {"decision": "approve"}
        )
        superuser_client.logout()
        token = mint_token(superuser.pk)

        assert_response(approve, HTTPStatus.FOUND, url=_code_redirect())
        assert_response(
            _exchange(client), HTTPStatus.OK, headers=NO_STORE, json=_token_body(token)
        )
        assert_response(
            _exchange(client), HTTPStatus.BAD_REQUEST, headers=NO_STORE, json=SPENT_CODE
        )
        assert_response(_post_mcp(client, "/mcp/", token), HTTPStatus.OK, json=PONG)
        assert_response(
            _post_mcp(client, "/mcp/organizer/", token),
            HTTPStatus.UNAUTHORIZED,
            json={"error": "A valid organizer Bearer token is required."},
        )


@pytest.mark.usefixtures("client_metadata", "fixed_code", "issued_code")
class TestTokenExchange:
    @pytest.fixture(name="issued_code")
    def issued_code_fixture(self, superuser_client):
        superuser_client.post(AUTHORIZE_URL, _params() | {"decision": "approve"})
        superuser_client.logout()

    @pytest.mark.parametrize(
        ("overrides", "description"),
        (
            (
                {"code_verifier": "w" * 43},
                "The code_verifier does not match the code_challenge.",
            ),
            (
                {"client_id": "https://other.example/metadata.json"},
                "The authorization code was issued to a different client.",
            ),
        ),
    )
    def test_mismatch_is_invalid_grant(self, client, overrides, description):
        assert_response(
            _exchange(client, **overrides),
            HTTPStatus.BAD_REQUEST,
            headers=NO_STORE,
            json={"error": "invalid_grant", "error_description": description},
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

    @pytest.mark.usefixtures("event")
    def test_manager_picks_event(self, manager_client):
        response = manager_client.get(
            AUTHORIZE_URL, _params(resource=ORGANIZER_RESOURCE)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(resource=ORGANIZER_RESOURCE, form=ANY),
        )

    def test_sphere_without_events_cannot_approve(self, manager_client):
        response = manager_client.get(
            AUTHORIZE_URL, _params(resource=ORGANIZER_RESOURCE)
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(
                resource=ORGANIZER_RESOURCE, can_approve=False
            ),
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
                resource=ORGANIZER_RESOURCE,
                may_grant=False,
                wants_event=False,
                can_approve=False,
            ),
        )

    @pytest.mark.usefixtures("event")
    def test_foreign_event_is_refused_without_code(self, manager_client, client):
        foreign = EventFactory(sphere=SphereFactory())

        response = manager_client.post(
            AUTHORIZE_URL,
            _params(resource=ORGANIZER_RESOURCE)
            | {"decision": "approve", "event": foreign.slug},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/authorize.html",
            context_data=_consent_context(resource=ORGANIZER_RESOURCE, form=ANY),
        )
        assert_response(
            _exchange(client), HTTPStatus.BAD_REQUEST, headers=NO_STORE, json=SPENT_CODE
        )

    @freeze_time("2026-09-25 12:00:00")
    def test_full_flow_yields_event_scoped_token(
        self, manager_client, client, manager, sphere, event
    ):
        approve = manager_client.post(
            AUTHORIZE_URL,
            _params(resource=ORGANIZER_RESOURCE)
            | {"decision": "approve", "event": event.slug},
        )
        manager_client.logout()
        token = mint_organizer_token(
            user_id=manager.pk, sphere_id=sphere.pk, event_id=event.pk
        )

        assert_response(approve, HTTPStatus.FOUND, url=_code_redirect())
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
