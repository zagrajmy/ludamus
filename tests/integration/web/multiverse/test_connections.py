from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY, MagicMock

import google.auth.exceptions
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Connection
from ludamus.links.docs_api import google as google_docs_api
from ludamus.pacts.multiverse import ConnectionDTO
from tests.integration.utils import assert_response

PRIOR_CHECK_AT = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _patch_google_refresh(monkeypatch, side_effect=None):
    """Patch the Google adapter at the SDK boundary.

    Lets the real `GoogleDocsApi.check_credentials` body run (so the
    adapter stays covered) without hitting the network. Pass a
    `RefreshError` to simulate auth failure or a `TransportError` to
    simulate network failure; default is a successful refresh.
    """
    creds = MagicMock()
    creds.refresh.side_effect = side_effect
    monkeypatch.setattr(google_docs_api, "_make_credentials", lambda *_a, **_kw: creds)


def _patch_google_factory_raises(monkeypatch, error):
    """Patch the Google adapter so the credential factory raises."""

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(google_docs_api, "_make_credentials", _raise)


PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "connections": "/multiverse/panel/connections/",
}
CONNECTIONS_PANEL_CONTEXT = {
    "events": [],
    "current_event": None,
    "is_proposal_active": False,
    "active_nav": "sphere-settings",
    "is_general_tab": False,
    "is_connections_tab": True,
    "tab_urls": TAB_URLS,
}


class TestConnectionsPageView:
    """Tests for /multiverse/panel/connections/ page."""

    url = reverse("multiverse:panel:connections")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/list.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "connections": []},
        )

    def test_get_returns_connections_scoped_to_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Konto Główne"
        )
        Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other Sphere"
        )

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/list.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "connections": [ConnectionDTO.model_validate(connection)],
            },
        )

    def test_get_orders_connections_by_display_name(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        Connection.objects.create(sphere=sphere, service="google", display_name="Zeta")
        Connection.objects.create(sphere=sphere, service="google", display_name="Alpha")
        Connection.objects.create(sphere=sphere, service="google", display_name="Mu")

        response = authenticated_client.get(self.url)

        names = [c.display_name for c in response.context["connections"]]
        assert names == ["Alpha", "Mu", "Zeta"]


class TestConnectionCreatePageView:
    """Tests for /multiverse/panel/connections/create/ page."""

    url = reverse("multiverse:panel:connection-create")

    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(self.url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )

    def test_post_redirects_anonymous_user_to_login(self, client):
        response = client.post(
            self.url, data={"service": "google", "display_name": "X"}
        )

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.post(
            self.url, data={"service": "google", "display_name": "X"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_rerenders_form_on_invalid_data(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data={"service": "google", "display_name": ""}
        )

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert not Connection.objects.filter(sphere=sphere).exists()

    def test_post_rejects_when_credentials_missing(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url, data={"service": "google", "display_name": "Konto"}
        )

        assert response.context["form"].errors.get("credentials")
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert not Connection.objects.filter(sphere=sphere).exists()

    def test_post_create_with_credentials_persists_blob_and_records_ok(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        _patch_google_refresh(monkeypatch)

        response = authenticated_client.post(
            self.url,
            data={
                "service": "google",
                "display_name": "Konto z kluczem",
                "credentials": '{"client": "abc"}',
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection created successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection = Connection.objects.get(sphere=sphere)
        stored = bytes(connection.credentials)
        assert stored
        assert b"abc" not in stored
        assert connection.last_check_status == "ok"

    def test_post_create_with_bad_credentials_leaves_no_row(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        _patch_google_refresh(
            monkeypatch, side_effect=google.auth.exceptions.RefreshError("bad key")
        )

        response = authenticated_client.post(
            self.url,
            data={
                "service": "google",
                "display_name": "Failing",
                "credentials": '{"client": "abc"}',
            },
        )

        # Form is re-rendered with the credential error (covers the
        # `except CredentialAuthError` arm in the create view).
        assert response.context["form"].non_field_errors()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert not Connection.objects.filter(sphere=sphere).exists()

    def test_post_create_rejects_duplicate_display_name(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        Connection.objects.create(sphere=sphere, service="google", display_name="Konto")
        _patch_google_refresh(monkeypatch)

        response = authenticated_client.post(
            self.url,
            data={
                "service": "google",
                "display_name": "Konto",
                "credentials": '{"client": "abc"}',
            },
        )

        assert response.context["form"].errors["display_name"] == [
            "A connection with this display name already exists."
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert (
            Connection.objects.filter(sphere=sphere, display_name="Konto").count() == 1
        )


class TestConnectionEditPageView:
    """Tests for /multiverse/panel/connections/<pk>/edit/ page."""

    @staticmethod
    def get_url(connection):
        return reverse("multiverse:panel:connection-edit", kwargs={"pk": connection.pk})

    def test_get_redirects_anonymous_user_to_login(self, client, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="X"
        )
        url = self.get_url(connection)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="X"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Konto"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/edit.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "form": ANY,
                "connection": ConnectionDTO.model_validate(connection),
            },
        )

    def test_get_redirects_when_connection_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )

    def test_post_updates_connection(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Old Name"
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={"service": "google", "display_name": "New Name"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection updated successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        assert connection.display_name == "New Name"

    def test_post_rejects_duplicate_display_name(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Original"
        )
        Connection.objects.create(sphere=sphere, service="google", display_name="Taken")

        response = authenticated_client.post(
            self.get_url(connection),
            data={"service": "google", "display_name": "Taken"},
        )

        assert response.context["form"].errors["display_name"] == [
            "A connection with this display name already exists."
        ]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/edit.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "form": ANY,
                "connection": ConnectionDTO.model_validate(connection),
            },
        )
        connection.refresh_from_db()
        assert connection.display_name == "Original"

    def test_post_rerenders_form_on_invalid_data(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Original"
        )

        response = authenticated_client.post(
            self.get_url(connection), data={"service": "google", "display_name": ""}
        )

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/edit.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "form": ANY,
                "connection": ConnectionDTO.model_validate(connection),
            },
        )
        connection.refresh_from_db()
        assert connection.display_name == "Original"

    def test_post_redirects_when_connection_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other"
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={"service": "google", "display_name": "Hacked"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        assert connection.display_name == "Other"

    def test_post_replace_credentials_off_skips_credentials(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Original",
            credentials=b"old-blob",
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Renamed",
                "credentials": "ignored",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection updated successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        assert connection.display_name == "Renamed"
        # Stored blob is left untouched when the toggle is off.
        assert bytes(connection.credentials) == b"old-blob"

    def test_post_replace_credentials_on_encrypts_and_persists(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Konto"
        )
        _patch_google_refresh(monkeypatch)

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Konto",
                "replace_credentials": "on",
                "credentials": '{"client": "abc"}',
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection updated successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        stored = bytes(connection.credentials)
        # Persisted blob must be non-empty and not contain the plaintext.
        assert stored
        assert b"abc" not in stored
        assert connection.last_check_status == "ok"

    def test_post_replace_credentials_keeps_prior_check_on_auth_failure(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Original",
            credentials=b"old-blob",
            last_check_status="ok",
            last_check_detail="prior pass",
            last_check_at=PRIOR_CHECK_AT,
        )
        # The view fetches the connection before attempting the update,
        # so the rendered DTO reflects the pre-update row.
        rendered_dto = ConnectionDTO.model_validate(connection)
        _patch_google_refresh(
            monkeypatch, side_effect=google.auth.exceptions.RefreshError("bad key")
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Renamed",
                "replace_credentials": "on",
                "credentials": '{"client": "abc"}',
            },
        )

        # Form is re-rendered with the credential error.
        assert response.context["form"].non_field_errors()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/edit.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "form": ANY,
                "connection": rendered_dto,
            },
        )
        connection.refresh_from_db()
        # Rejected credential never persisted, so the prior good check
        # (and the existing credential / display name) survive intact.
        assert connection.last_check_status == "ok"
        assert connection.last_check_detail == "prior pass"
        assert connection.last_check_at == PRIOR_CHECK_AT
        assert connection.display_name == "Original"
        assert bytes(connection.credentials) == b"old-blob"

    def test_post_replace_credentials_keeps_prior_check_on_invalid_json(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Konto",
            last_check_status="ok",
            last_check_detail="prior pass",
            last_check_at=PRIOR_CHECK_AT,
        )
        # No SDK patching — JSON decoding inside the adapter fails first.
        # Patch _make_credentials anyway so a stray call would surface as
        # an obvious test error rather than a network attempt.
        _patch_google_factory_raises(monkeypatch, RuntimeError("should not run"))

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Konto",
                "replace_credentials": "on",
                "credentials": "not json",
            },
        )

        assert response.context["form"].non_field_errors()
        assert response.status_code == HTTPStatus.OK
        connection.refresh_from_db()
        assert connection.last_check_status == "ok"
        assert connection.last_check_detail == "prior pass"
        assert connection.last_check_at == PRIOR_CHECK_AT

    def test_post_replace_credentials_keeps_prior_check_on_factory_rejection(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Konto",
            last_check_status="ok",
            last_check_detail="prior pass",
            last_check_at=PRIOR_CHECK_AT,
        )
        _patch_google_factory_raises(monkeypatch, ValueError("missing key"))

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Konto",
                "replace_credentials": "on",
                "credentials": '{"client": "abc"}',
            },
        )

        assert response.context["form"].non_field_errors()
        assert response.status_code == HTTPStatus.OK
        connection.refresh_from_db()
        assert connection.last_check_status == "ok"
        assert connection.last_check_detail == "prior pass"
        assert connection.last_check_at == PRIOR_CHECK_AT

    def test_post_replace_credentials_keeps_prior_check_on_transport_error(
        self, authenticated_client, active_user, sphere, monkeypatch
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Konto",
            last_check_status="ok",
            last_check_detail="prior pass",
            last_check_at=PRIOR_CHECK_AT,
        )
        _patch_google_refresh(
            monkeypatch, side_effect=google.auth.exceptions.TransportError("timeout")
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Konto",
                "replace_credentials": "on",
                "credentials": '{"client": "abc"}',
            },
        )

        assert response.context["form"].non_field_errors()
        assert response.status_code == HTTPStatus.OK
        connection.refresh_from_db()
        assert connection.last_check_status == "ok"
        assert connection.last_check_detail == "prior pass"
        assert connection.last_check_at == PRIOR_CHECK_AT

    def test_post_replace_credentials_on_requires_credentials(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Konto",
            credentials=b"unchanged",
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "service": "google",
                "display_name": "Konto",
                "replace_credentials": "on",
                "credentials": "",
            },
        )

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/edit.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "form": ANY,
                "connection": ConnectionDTO.model_validate(connection),
            },
        )
        connection.refresh_from_db()
        assert bytes(connection.credentials) == b"unchanged"


class TestConnectionDeletePageView:
    """Tests for /multiverse/panel/connections/<pk>/do/delete/ page."""

    @staticmethod
    def get_url(connection):
        return reverse(
            "multiverse:panel:connection-delete", kwargs={"pk": connection.pk}
        )

    def test_get_redirects_anonymous_user_to_login(self, client, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="X"
        )
        url = self.get_url(connection)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="X"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_renders_confirm_page_for_sphere_manager(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="To delete"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/delete.html",
            context_data={
                **CONNECTIONS_PANEL_CONTEXT,
                "connection": ConnectionDTO.model_validate(connection),
            },
        )

    def test_get_redirects_when_connection_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other"
        )

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )

    def test_post_deletes_connection(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Goner"
        )

        response = authenticated_client.post(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection deleted successfully.")],
            url="/multiverse/panel/connections/",
        )
        assert not Connection.objects.filter(pk=connection.pk).exists()

    def test_post_redirects_when_connection_belongs_to_other_sphere(
        self, authenticated_client, active_user, sphere, non_root_sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other"
        )

        response = authenticated_client.post(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )
        assert Connection.objects.filter(pk=connection.pk).exists()
