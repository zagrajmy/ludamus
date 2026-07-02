from http import HTTPStatus

import pytest
from django.conf import settings
from django.test import RequestFactory
from django.urls import resolve


@pytest.mark.skipif(not settings.DEBUG, reason="Debug URL patterns are DEBUG-only")
class TestDebugUrlPatterns:
    def test_debug_404_route(self):
        request = RequestFactory().get("/404/")

        response = resolve("/404/").func(request)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_debug_500_route(self):
        request = RequestFactory().get("/500/")

        response = resolve("/500/").func(request)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
