import pytest

from ludamus.mills.external_tools import ExternalToolService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.external_tools import ExternalToolDTO

TABLE_MANAGER = ExternalToolDTO(
    name="Table Manager",
    slug="table-manager",
    url="https://tables.example.org/start",
    allowed_domains=["login.example.org"],
)


class FakeExternalTools:
    def __init__(self, *tools):
        self._tools = {tool.slug: tool for tool in tools}

    def read_active(self, slug):
        try:
            return self._tools[slug]
        except KeyError as exception:
            raise NotFoundError from exception


class TestExternalToolService:
    def test_read_active_returns_the_active_tool(self):
        service = ExternalToolService(FakeExternalTools(TABLE_MANAGER))

        tool = service.read_active("table-manager")

        assert tool == TABLE_MANAGER

    def test_read_active_raises_not_found_for_an_unknown_slug(self):
        service = ExternalToolService(FakeExternalTools(TABLE_MANAGER))

        with pytest.raises(NotFoundError):
            service.read_active("missing")
