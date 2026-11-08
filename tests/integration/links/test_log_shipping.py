import logging
import threading
from http import HTTPStatus
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)

from ludamus.links.analytics.log_shipping import posthog_handler

TOKEN_SEGMENT = "A" * 30 + "-" + "b" * 33
PROJECT_KEY = "phc_test_project_key"
RAY_ID = "8bf7ec2d1234abcd-WAW"
INTEGRATION_ID = 7


RECEIVED: list[tuple[str, str, bytes]] = []


def _receiver(environ, start_response):
    body = environ["wsgi.input"].read(int(environ["CONTENT_LENGTH"]))
    RECEIVED.append((environ["PATH_INFO"], environ["HTTP_AUTHORIZATION"], body))
    start_response(f"{HTTPStatus.OK} OK", [])
    return [b""]


class _Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(name="ship")
def ship_fixture(settings):
    """Route logging to a local OTLP receiver standing in for PostHog."""
    RECEIVED.clear()
    server = make_server("127.0.0.1", 0, _receiver, handler_class=_Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings.POSTHOG_API_KEY = PROJECT_KEY
    settings.POSTHOG_HOST = f"http://127.0.0.1:{server.server_port}"
    handler = posthog_handler()
    loggers = [logging.getLogger(), logging.getLogger("django")]
    for logger in loggers:
        logger.addHandler(handler)

    def shipped():
        handler.flush()
        return [
            (resource_logs, scope_logs.scope.name, record)
            for _, _, body in RECEIVED
            for resource_logs in ExportLogsServiceRequest.FromString(body).resource_logs
            for scope_logs in resource_logs.scope_logs
            for record in scope_logs.log_records
        ]

    yield shipped
    for logger in loggers:
        logger.removeHandler(handler)
    handler.close()
    server.shutdown()


def _value(any_value):
    return getattr(any_value, any_value.WhichOneof("value"))


def _attributes(key_values):
    return {kv.key: _value(kv.value) for kv in key_values}


def _from(shipped, scope):
    return [record for _, name, record in shipped if name == scope]


def _fail():
    raise ValueError("bad row")


def _fail_at(url):
    message = f"no claim at {url}"
    raise ValueError(message)


class TestPosthogHandler:
    def test_without_a_project_key_nothing_is_shipped(self, settings):
        settings.POSTHOG_API_KEY = ""

        assert isinstance(posthog_handler(), logging.NullHandler)

    def test_records_reach_posthog_logs_with_the_project_key(self, ship):
        logging.getLogger("ludamus.mills.konwencik").warning(
            "export stalled", extra={"integration_id": INTEGRATION_ID}
        )
        shipped = ship()

        assert {(path, auth) for path, auth, _ in RECEIVED} == {
            ("/i/v1/logs", f"Bearer {PROJECT_KEY}")
        }
        ((resource_logs, scope, record),) = [
            row for row in shipped if row[1] == "mills.konwencik"
        ]
        resource = _attributes(resource_logs.resource.attributes)
        assert resource["service.name"] == "ludamus"
        assert resource["deployment.environment"] == "test"
        assert scope == "mills.konwencik"
        assert _value(record.body) == "export stalled"
        assert record.severity_text == "WARNING"
        assert _attributes(record.attributes)["integration_id"] == INTEGRATION_ID

    def test_an_exception_ships_its_type_and_traceback(self, ship):
        try:
            _fail()
        except ValueError:
            logging.getLogger("ludamus.mills.integrations").exception("Sync failed")

        (record,) = _from(ship(), "mills.integrations")
        attributes = _attributes(record.attributes)
        assert _value(record.body) == "Sync failed"
        assert attributes["exception.type"] == "ValueError"
        assert attributes["exception.stacktrace"].startswith("Traceback")

    def test_a_bearer_token_in_a_field_or_traceback_is_redacted(self, ship):
        url = f"/claim/{TOKEN_SEGMENT}/"
        try:
            _fail_at(url)
        except ValueError:
            logging.getLogger("ludamus.gates.crowd").exception(
                "Claim failed", extra={"next": url}
            )

        (record,) = _from(ship(), "gates.crowd")
        attributes = _attributes(record.attributes)
        assert attributes["next"] == "/claim/:token/"
        assert TOKEN_SEGMENT not in attributes["exception.stacktrace"]

    def test_the_exporter_s_own_lines_are_not_shipped_back(self, ship):
        logging.getLogger("opentelemetry.exporter.otlp").warning("export failed")

        assert _from(ship(), "opentelemetry.exporter.otlp") == []

    def test_what_the_transport_logs_during_an_export_is_not_shipped(
        self, ship, caplog
    ):
        caplog.set_level(logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)
        logging.getLogger("ludamus.mills.listing").warning("first")
        ship()

        logging.getLogger("ludamus.mills.listing").warning("second")
        shipped = ship()

        assert [name for _, name, _ in shipped] == ["mills.listing", "mills.listing"]

    def test_a_malformed_log_call_is_reported_not_raised(self, ship, caplog):
        # Straight to the handler: pytest's own capture handler re-raises a
        # formatting error by design, which would mask what ours does.
        record = logging.getLogger("ludamus.mills.listing").makeRecord(
            "ludamus.mills.listing",
            logging.WARNING,
            __file__,
            1,
            "%s and %s",
            ("one",),
            None,
        )

        posthog_handler().handle(record)

        assert _from(ship(), "mills.listing") == []
        assert [
            r.getMessage() for r in caplog.records if r.name.endswith("shipping")
        ] == ["Could not ship a ludamus.mills.listing record"]

    def test_debug_lines_stay_on_stdout(self, ship, caplog):
        caplog.set_level(logging.DEBUG)
        logging.getLogger("ludamus.inits.middleware").debug("language changed")

        assert _from(ship(), "inits.middleware") == []


@pytest.mark.django_db
class TestShippedRequests:
    def test_the_wide_event_ships_as_attributes_without_empty_fields(
        self, client, ship, caplog
    ):
        caplog.set_level(logging.INFO)

        client.get("/", HTTP_CF_RAY=RAY_ID)

        (record,) = _from(ship(), "wide_event")
        attributes = _attributes(record.attributes)
        assert attributes["ray_id"] == RAY_ID
        assert attributes["status"] == HTTPStatus.OK
        assert attributes["view"] == "web:index"
        assert "user_id" not in attributes
        assert not [r for r in caplog.records if r.name.startswith("opentelemetry")]

    def test_a_bearer_token_in_a_logged_path_is_redacted(self, client, ship):
        client.get(f"/claim/{TOKEN_SEGMENT}/")

        (record,) = _from(ship(), "django.request")
        attributes = _attributes(record.attributes)
        assert _value(record.body) == "Not Found: /claim/:token/"
        assert "request" not in attributes
        assert attributes["status_code"] == HTTPStatus.NOT_FOUND
