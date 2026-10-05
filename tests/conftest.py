import zoneinfo

import pytest
from django.conf import settings as django_settings
from django.db import connection


def pytest_configure(config):
    # django_settings, not the `settings` fixture the one fixture below takes:
    # ruff forbids a function-level import, so the name has to be aliased.
    # Catches a stray export in any pytest run. The e2e server is not covered:
    # Playwright never loads this file, so `.env.e2e`'s pin is the only thing
    # standing between that runserver process and the live project.
    if django_settings.POSTHOG_API_KEY:
        raise pytest.UsageError(
            "POSTHOG_API_KEY is set; tests would report to a real PostHog "
            "project. Unset it, or check the pin in .env.test / .env.e2e."
        )

    config.addinivalue_line(
        "markers",
        "postgres: test requires the PostgreSQL backend (e.g. select_for_update "
        "row locking, which is a no-op and flaky on SQLite). Run via "
        "`mise run test:postgres`; auto-skipped on other backends.",
    )


def pytest_collection_modifyitems(items):
    if connection.vendor == "postgresql":
        return
    skip_postgres = pytest.mark.skip(
        reason="requires the PostgreSQL backend (run `mise run test:postgres`)"
    )
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_postgres)


@pytest.fixture
def time_zone(settings):
    return zoneinfo.ZoneInfo(settings.TIME_ZONE)
