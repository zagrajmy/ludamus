import pytest


@pytest.fixture(name="board_settings", autouse=True)
def _board_settings(settings):
    # Tests run with no Worker host; the signing key falls back to the
    # committed dev pair, the one the Worker verifies with locally.
    settings.BOARD_HOST = "localhost:8788"
    return settings
