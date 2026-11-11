import importlib
from http import HTTPStatus

import pytest
from django.test import RequestFactory, override_settings
from django.urls import Resolver404, clear_url_caches, resolve

from ludamus.gates.web.django import urls


@pytest.fixture(name="debug_urlconf")
def debug_urlconf_fixture():
    # NOTE: the DEBUG-only routes are appended when the URLconf module is
    # imported, so the module has to be re-imported under DEBUG and again
    # after it to leave the other tests the production routes.
    with override_settings(DEBUG=True):
        importlib.reload(urls)
        clear_url_caches()
        yield
    importlib.reload(urls)
    clear_url_caches()


@pytest.mark.usefixtures("debug_urlconf")
class TestDebugUrlPatterns:
    def test_debug_404_route(self):
        request = RequestFactory().get("/404/")

        response = resolve("/404/").func(request)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_debug_500_route(self):
        request = RequestFactory().get("/500/")

        response = resolve("/500/").func(request)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_debug_routes_absent_outside_debug():
    with pytest.raises(Resolver404):
        resolve("/500/")
