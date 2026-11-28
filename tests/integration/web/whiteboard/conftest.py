import pytest

LITTLE_TABLE = "https://littletable.example.com"


@pytest.fixture(name="board_settings", autouse=True)
def _board_settings(settings):
    settings.LITTLE_TABLE_URL = LITTLE_TABLE
    return settings
