from unittest.mock import Mock, patch

import pytest
from django.http import HttpResponseRedirect
from django.urls import reverse

from ludamus.adapters.web.django.middlewares import (
    RedirectErrorMiddleware,
    RequestContextMiddleware,
)
from ludamus.inits import DependencyInjector, RepositoryInjectionMiddleware
from ludamus.inits.middleware import SUBSCRIBED_SPHERES_SESSION_KEY
from ludamus.links.db.django.models import NotificationSubscription, Sphere
from ludamus.links.db.django.uow import UnitOfWork
from ludamus.pacts import RedirectError, RequestContext


@pytest.fixture(name="get_response_mock")
def get_response_mock_fixture():
    return Mock()


class TestRequestContextMiddleware:

    @pytest.fixture
    @staticmethod
    def middleware(get_response_mock):
        return RequestContextMiddleware(get_response_mock)

    @pytest.mark.django_db
    @staticmethod
    def test_successful_sphere_lookup(
        get_response_mock, middleware, rf, sphere, settings
    ):
        request = rf.get("/")
        request.META["HTTP_HOST"] = sphere.site.domain
        request.di = DependencyInjector()
        root_sphere = Sphere.objects.get(site__domain=settings.ROOT_DOMAIN)

        sphere.site.sphere = sphere

        middleware(request)

        assert request.context == RequestContext(
            current_site_id=sphere.site.id,
            current_sphere_id=sphere.id,
            root_site_id=root_sphere.site.id,
            root_sphere_id=root_sphere.id,
        )
        get_response_mock.assert_called_once_with(request)

    @pytest.mark.django_db
    @staticmethod
    @pytest.mark.parametrize(
        "host",
        (
            "127.0.0.1:1355",
            "filters-bar.skip-steps.localhost:1355",
            "filters-bar.skip-steps.local:1355",
        ),
    )
    def test_unknown_local_host_uses_root_sphere_in_development(
        host, get_response_mock, middleware, rf, settings
    ):
        settings.ENV = "development"
        settings.ALLOWED_HOSTS.extend(
            [".localhost", ".local", "localhost", "127.0.0.1"]
        )
        request = rf.get("/")
        request.META["HTTP_HOST"] = host
        request.di = DependencyInjector()
        root_sphere = Sphere.objects.get(site__domain=settings.ROOT_DOMAIN)

        middleware(request)

        assert request.context == RequestContext(
            current_site_id=root_sphere.site.id,
            current_sphere_id=root_sphere.id,
            root_site_id=root_sphere.site.id,
            root_sphere_id=root_sphere.id,
        )
        get_response_mock.assert_called_once_with(request)

    @pytest.mark.django_db
    @staticmethod
    def test_site_does_not_exist_redirects(
        middleware, get_response_mock, rf, settings, sphere
    ):
        settings.ALLOWED_HOSTS.append("nonexistent.example.com")
        request = rf.get("/")
        request.META["HTTP_HOST"] = "nonexistent.example.com"
        request.di = DependencyInjector()

        with patch("ludamus.adapters.web.django.middlewares.messages") as mock_messages:
            response = middleware(request)

            assert isinstance(response, HttpResponseRedirect)
            expected_url = f"http://{sphere.site.domain}{reverse('web:index')}"
            assert response.url == expected_url
            mock_messages.error.assert_called_once()
            get_response_mock.assert_not_called()

    @staticmethod
    @pytest.mark.parametrize(
        "path", ("/static/test.css", "/admin/", "/__debug__/toolbar/", "/__reload__/")
    )
    def test_skips_processing_for_excluded_paths(
        middleware, get_response_mock, rf, path, settings
    ):
        """Middleware skips context setup for paths in MIDDLEWARE_SKIP_PREFIXES."""
        assert any(path.startswith(p) for p in settings.MIDDLEWARE_SKIP_PREFIXES)
        request = rf.get(path)

        middleware(request)

        # Should pass through without setting context
        assert not hasattr(request, "context")
        get_response_mock.assert_called_once_with(request)


class TestRepositoryInjectionMiddleware:
    @pytest.fixture
    @staticmethod
    def middleware(get_response_mock):
        return RepositoryInjectionMiddleware(get_response_mock)

    @staticmethod
    def test_injects_uow_for_normal_requests(middleware, get_response_mock, rf):
        request = rf.get("/some/page/")

        middleware(request)

        assert hasattr(request, "di")
        assert isinstance(request.di.uow, UnitOfWork)
        get_response_mock.assert_called_once_with(request)

    @staticmethod
    @pytest.mark.parametrize(
        "path", ("/static/test.css", "/admin/", "/__debug__/toolbar/", "/__reload__/")
    )
    def test_skips_uow_for_excluded_paths(
        middleware, get_response_mock, rf, path, settings
    ):
        """Middleware skips UoW creation for paths in MIDDLEWARE_SKIP_PREFIXES."""
        assert any(path.startswith(p) for p in settings.MIDDLEWARE_SKIP_PREFIXES)
        request = rf.get(path)

        middleware(request)

        assert not hasattr(request, "di")
        get_response_mock.assert_called_once_with(request)


class TestRedirectErrorMiddleware:
    @pytest.fixture
    @staticmethod
    def middleware(get_response_mock):
        return RedirectErrorMiddleware(get_response_mock)

    @staticmethod
    def test_normal_request_processing(middleware, get_response_mock, rf):

        request = rf.get("/")

        middleware(request)

        get_response_mock.assert_called_once_with(request)

    @staticmethod
    def test_redirect_error_with_error_message(middleware, rf):
        request = rf.get("/")
        error_url = "/error-redirect/"
        error_message = "Test error message"
        exception = RedirectError(url=error_url, error=error_message)

        with patch(
            "ludamus.adapters.web.django.middlewares.messages.error"
        ) as mock_messages_error:
            response = middleware.process_exception(request, exception)

            assert isinstance(response, HttpResponseRedirect)
            assert response.url == error_url
            mock_messages_error.assert_called_once_with(request, error_message)

    @staticmethod
    def test_redirect_error_with_warning_message(middleware, rf):

        request = rf.get("/")
        error_url = "/warning-redirect/"
        warning_message = "Test warning message"
        exception = RedirectError(url=error_url, warning=warning_message)

        with patch(
            "ludamus.adapters.web.django.middlewares.messages.warning"
        ) as mock_messages_warning:
            response = middleware.process_exception(request, exception)

            assert isinstance(response, HttpResponseRedirect)
            assert response.url == error_url
            mock_messages_warning.assert_called_once_with(request, warning_message)

    @staticmethod
    def test_redirect_error_with_both_error_and_warning(middleware, rf):

        request = rf.get("/")
        error_url = "/both-messages-redirect/"
        error_message = "Test error message"
        warning_message = "Test warning message"
        exception = RedirectError(
            url=error_url, error=error_message, warning=warning_message
        )

        with (
            patch(
                "ludamus.adapters.web.django.middlewares.messages.error"
            ) as mock_messages_error,
            patch(
                "ludamus.adapters.web.django.middlewares.messages.warning"
            ) as mock_messages_warning,
        ):
            response = middleware.process_exception(request, exception)

            assert isinstance(response, HttpResponseRedirect)
            assert response.url == error_url
            mock_messages_error.assert_called_once_with(request, error_message)
            mock_messages_warning.assert_called_once_with(request, warning_message)

    @staticmethod
    def test_redirect_error_without_messages(middleware, rf):

        request = rf.get("/")
        error_url = "/no-message-redirect/"
        exception = RedirectError(url=error_url)

        with (
            patch(
                "ludamus.adapters.web.django.middlewares.messages.error"
            ) as mock_messages_error,
            patch(
                "ludamus.adapters.web.django.middlewares.messages.warning"
            ) as mock_messages_warning,
        ):
            response = middleware.process_exception(request, exception)

            assert isinstance(response, HttpResponseRedirect)
            assert response.url == error_url
            mock_messages_error.assert_not_called()
            mock_messages_warning.assert_not_called()

    @staticmethod
    def test_non_redirect_error_returns_none(middleware, rf):

        request = rf.get("/")
        exception = ValueError("Not a redirect error")

        response = middleware.process_exception(request, exception)

        assert response is None


class TestSphereVisitSubscriptionMiddleware:
    URL = reverse("web:crowd:profile")

    @pytest.mark.django_db
    def test_anonymous_request_subscribes_nothing(self, client):
        client.get(self.URL)

        assert not NotificationSubscription.objects.exists()

    def test_authenticated_request_subscribes_to_visited_sphere(
        self, authenticated_client, active_user, sphere
    ):
        authenticated_client.get(self.URL)

        subscription = NotificationSubscription.objects.get()
        assert subscription.user_id == active_user.pk
        assert subscription.sphere_id == sphere.pk
        assert subscription.source == "visit"

    def test_flagged_session_skips_the_write(self, authenticated_client):
        authenticated_client.get(self.URL)
        NotificationSubscription.objects.all().delete()

        authenticated_client.get(self.URL)

        assert not NotificationSubscription.objects.exists()

    def test_fresh_session_revisit_keeps_mute(
        self, authenticated_client, active_user, sphere
    ):
        authenticated_client.get(self.URL)
        NotificationSubscription.objects.update(muted=True)
        session = authenticated_client.session
        del session[SUBSCRIBED_SPHERES_SESSION_KEY]
        session.save()

        authenticated_client.get(self.URL)

        subscription = NotificationSubscription.objects.get()
        assert subscription.user_id == active_user.pk
        assert subscription.muted is True
