from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Connection
from ludamus.pacts.multiverse import ConnectionDTO
from tests.integration.utils import assert_response

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
            sphere=sphere, display_name="Konto Główne"
        )
        Connection.objects.create(sphere=non_root_sphere, display_name="Other Sphere")

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
        Connection.objects.create(sphere=sphere, display_name="Zeta")
        Connection.objects.create(sphere=sphere, display_name="Alpha")
        Connection.objects.create(sphere=sphere, display_name="Mu")

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
        response = client.post(self.url, data={"display_name": "X"})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={self.url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.post(self.url, data={"display_name": "X"})

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

        response = authenticated_client.post(self.url, data={"display_name": ""})

        assert response.context["form"].errors
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert not Connection.objects.filter(sphere=sphere).exists()

    def test_post_rejects_when_secret_missing(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.url, data={"display_name": "Konto"})

        assert response.context["form"].errors.get("secret")
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/connections/create.html",
            context_data={**CONNECTIONS_PANEL_CONTEXT, "form": ANY},
        )
        assert not Connection.objects.filter(sphere=sphere).exists()

    def test_post_create_with_secret_persists_blob(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.url,
            data={"display_name": "Konto z kluczem", "secret": '{"client": "abc"}'},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection created successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection = Connection.objects.get(sphere=sphere)
        stored = bytes(connection.secret)
        assert stored
        assert b"abc" not in stored


class TestConnectionEditPageView:
    """Tests for /multiverse/panel/connections/<pk>/edit/ page."""

    @staticmethod
    def get_url(connection):
        return reverse("multiverse:panel:connection-edit", kwargs={"pk": connection.pk})

    def test_get_redirects_anonymous_user_to_login(self, client, sphere):
        connection = Connection.objects.create(sphere=sphere, display_name="X")
        url = self.get_url(connection)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, sphere):
        connection = Connection.objects.create(sphere=sphere, display_name="X")

        response = authenticated_client.get(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(sphere=sphere, display_name="Konto")

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
            sphere=non_root_sphere, display_name="Other"
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
        connection = Connection.objects.create(sphere=sphere, display_name="Old Name")

        response = authenticated_client.post(
            self.get_url(connection), data={"display_name": "New Name"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection updated successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        assert connection.display_name == "New Name"

    def test_post_rerenders_form_on_invalid_data(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(sphere=sphere, display_name="Original")

        response = authenticated_client.post(
            self.get_url(connection), data={"display_name": ""}
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
            sphere=non_root_sphere, display_name="Other"
        )

        response = authenticated_client.post(
            self.get_url(connection), data={"display_name": "Hacked"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        assert connection.display_name == "Other"

    def test_post_replace_secret_off_skips_secret(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, display_name="Original", secret=b"old-blob"
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={"display_name": "Renamed", "secret": "ignored"},
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
        assert bytes(connection.secret) == b"old-blob"

    def test_post_replace_secret_on_encrypts_and_persists(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(sphere=sphere, display_name="Konto")

        response = authenticated_client.post(
            self.get_url(connection),
            data={
                "display_name": "Konto",
                "replace_secret": "on",
                "secret": '{"client": "abc"}',
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Connection updated successfully.")],
            url="/multiverse/panel/connections/",
        )
        connection.refresh_from_db()
        stored = bytes(connection.secret)
        # Persisted blob must be non-empty and not contain the plaintext.
        assert stored
        assert b"abc" not in stored

    def test_post_replace_secret_on_requires_secret(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        connection = Connection.objects.create(
            sphere=sphere, display_name="Konto", secret=b"unchanged"
        )

        response = authenticated_client.post(
            self.get_url(connection),
            data={"display_name": "Konto", "replace_secret": "on", "secret": ""},
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
        assert bytes(connection.secret) == b"unchanged"


class TestConnectionDeletePageView:
    """Tests for /multiverse/panel/connections/<pk>/do/delete/ page."""

    @staticmethod
    def get_url(connection):
        return reverse(
            "multiverse:panel:connection-delete", kwargs={"pk": connection.pk}
        )

    def test_get_redirects_anonymous_user_to_login(self, client, sphere):
        connection = Connection.objects.create(sphere=sphere, display_name="X")
        url = self.get_url(connection)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, sphere):
        connection = Connection.objects.create(sphere=sphere, display_name="X")

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
        connection = Connection.objects.create(sphere=sphere, display_name="To delete")

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
            sphere=non_root_sphere, display_name="Other"
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
        connection = Connection.objects.create(sphere=sphere, display_name="Goner")

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
            sphere=non_root_sphere, display_name="Other"
        )

        response = authenticated_client.post(self.get_url(connection))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Connection not found.")],
            url="/multiverse/panel/connections/",
        )
        assert Connection.objects.filter(pk=connection.pk).exists()
