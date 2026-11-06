import json
import logging
import os
import sys
from http import HTTPStatus
from importlib import import_module

import pytest
from django.conf import settings as django_settings
from django.http import HttpResponse
from django.urls import path

from ludamus.gates.web.django.wide_event import WideEventMiddleware
from ludamus.links.analytics.log_format import JsonFormatter
from tests.integration.utils import assert_response

LOGGER = WideEventMiddleware.logger.name
RAY_ID = "8bf7ec2d1234abcd-WAW"
UUID_HEX_LENGTH = 32
INTEGRATION_ID = 7


def _boom(_request):
    raise RuntimeError("payment provider down")


urlpatterns = [
    path("wide-event-boom/", _boom, name="wide_event_boom"),
    *import_module(django_settings.ROOT_URLCONF).urlpatterns,
]


@pytest.fixture(name="events")
def events_fixture(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    return caplog


def _wide_events(caplog):
    return [record for record in caplog.records if record.name == LOGGER]


@pytest.mark.django_db
class TestWideEventMiddleware:
    def test_one_event_per_request_carries_the_request_context(
        self, authenticated_client, active_user, sphere, events
    ):
        authenticated_client.get("/", HTTP_CF_RAY=RAY_ID)

        (event,) = _wide_events(events)
        assert event.ray_id == RAY_ID
        assert event.environment == "test"
        assert event.commit == django_settings.COMMIT_SHA
        assert event.worker == os.getpid()
        assert event.method == "GET"
        assert event.path == "/"
        assert event.view == "web:index"
        assert event.status == HTTPStatus.OK
        assert event.outcome == "success"
        assert event.sphere_id == sphere.pk
        assert event.user_id == active_user.pk
        assert event.language == "en"
        assert event.htmx is False
        assert event.duration_ms >= 0
        assert event.db_queries >= 1
        assert event.db_ms >= 0

    def test_a_view_fault_is_one_error_event_and_still_a_500(
        self, client, settings, events
    ):
        settings.ROOT_URLCONF = __name__
        client.raise_request_exception = False

        response = client.get("/wide-event-boom/")

        assert_response(response, HTTPStatus.INTERNAL_SERVER_ERROR)
        (event,) = _wide_events(events)
        assert event.status == HTTPStatus.INTERNAL_SERVER_ERROR
        assert event.outcome == "error"
        assert event.error_type == "RuntimeError"
        assert event.error_message == "payment provider down"
        assert event.view == "wide_event_boom"
        assert event.user_id is None
        assert len(event.ray_id) == UUID_HEX_LENGTH

    def test_static_and_health_requests_emit_nothing(self, client, rf, events):
        client.get("/healthz/")
        WideEventMiddleware(lambda _request: HttpResponse())(rf.get("/static/app.css"))

        assert _wide_events(events) == []

    def test_the_event_renders_as_one_json_line(self, client, sphere, events):
        client.get("/", HTTP_CF_RAY=RAY_ID)

        (event,) = _wide_events(events)
        line = JsonFormatter().format(event)

        assert "\n" not in line
        payload = json.loads(line)
        assert payload["ray_id"] == RAY_ID
        assert payload["sphere_id"] == sphere.pk
        assert payload["level"] == "INFO"
        assert payload["logger"] == LOGGER
        assert payload["ts"].endswith("+00:00")
        assert {"args", "msg", "exc_info", "levelno"}.isdisjoint(payload)


def _failing_exc_info():
    try:
        _fail()
    except ValueError:
        return sys.exc_info()
    raise AssertionError


def _fail():
    raise ValueError("bad value")


class TestJsonFormatter:
    def test_extra_fields_and_the_traceback_land_in_the_payload(self):
        logger = logging.getLogger("tests.json_formatter")
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            __file__,
            1,
            "Could not sync %s",
            ("konwencik",),
            exc_info=_failing_exc_info(),
            extra={"integration_id": INTEGRATION_ID},
        )

        payload = json.loads(JsonFormatter().format(record))

        assert payload["message"] == "Could not sync konwencik"
        assert payload["level"] == "ERROR"
        assert payload["integration_id"] == INTEGRATION_ID
        assert payload["exception"].startswith("Traceback")
        assert payload["exception"].rstrip().endswith("ValueError: bad value")

    def test_an_unserialisable_field_is_stringified_not_dropped(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", (), None)
        record.when = object()

        payload = json.loads(JsonFormatter().format(record))

        assert payload["when"].startswith("<object object")
