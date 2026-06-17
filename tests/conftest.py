import logging
import zoneinfo

import pytest
from django.db import connection

from tests.template_checks import MissingTemplateVariableFilter


def pytest_configure(config):
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


@pytest.fixture(autouse=True)
def _fail_on_missing_template_variables():
    """Raise exception when template variables cannot be resolved.

    Django silently swallows AttributeError when accessing missing
    methods/properties on template objects. This fixture ensures
    such errors are caught during tests.
    """
    logger = logging.getLogger("django.template")
    original_level = logger.level
    filter_instance = MissingTemplateVariableFilter()

    logger.setLevel(logging.DEBUG)
    logger.addFilter(filter_instance)

    yield

    logger.removeFilter(filter_instance)
    logger.setLevel(original_level)


@pytest.fixture
def time_zone(settings):
    return zoneinfo.ZoneInfo(settings.TIME_ZONE)


@pytest.fixture(autouse=True)
def english_language(settings):
    settings.LANGUAGE_CODE = "en"


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
