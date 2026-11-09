import pytest

from tests.integration.web.parley.helpers import configure_parley


@pytest.fixture(name="parley_settings")
def _parley_settings(settings):
    return configure_parley(settings)
