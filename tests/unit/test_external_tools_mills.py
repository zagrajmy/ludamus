import pytest

from ludamus.mills.external_tools import ExternalToolService
from ludamus.pacts.errors import NotFoundError


class MissingToolRepository:
    @staticmethod
    def read_active(_slug):
        raise NotFoundError


class TestExternalToolService:
    def test_read_active_lets_an_unknown_tool_surface_as_not_found(self):
        service = ExternalToolService(MissingToolRepository())

        with pytest.raises(NotFoundError):
            service.read_active("missing")
