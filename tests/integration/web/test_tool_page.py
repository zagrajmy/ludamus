from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.edges.settings import CSP_POLICY
from ludamus.links.db.django.models import ExternalTool
from ludamus.pacts.external_tools import ExternalToolDTO
from tests.integration.utils import assert_response, assert_response_404

ENFORCE_HEADER = "Content-Security-Policy"


@pytest.fixture(name="tool")
def tool_fixture():
    return ExternalTool.objects.create(
        name="Table Manager",
        slug="table-manager",
        url="https://tables.example.org/start",
        allowed_domains="login.example.org\ncdn.example.org",
    )


def _assert_tool_page(response) -> None:
    assert_response(
        response,
        HTTPStatus.OK,
        template_name="tools/page.html",
        context_data={
            "tool": ExternalToolDTO(
                name="Table Manager",
                slug="table-manager",
                url="https://tables.example.org/start",
                frame_hosts=[
                    "tables.example.org",
                    "login.example.org",
                    "cdn.example.org",
                ],
            )
        },
    )


class TestToolPage:
    def test_shows_the_tool_on_a_sphere(self, client, tool, non_root_sphere):
        response = client.get(
            reverse("web:tool", kwargs={"slug": tool.slug}),
            HTTP_HOST=non_root_sphere.site.domain,
        )

        _assert_tool_page(response)

    def test_policy_lets_the_frame_load_only_the_tool_domains(
        self, client, settings, tool
    ):
        settings.SECURE_CSP = CSP_POLICY

        response = client.get(reverse("web:tool", kwargs={"slug": tool.slug}))

        _assert_tool_page(response)
        assert (
            "frame-src https://tables.example.org https://login.example.org "
            "https://cdn.example.org;"
        ) in f"{response.headers[ENFORCE_HEADER]};"

    def test_no_policy_is_sent_where_the_site_sends_none(self, client, tool):
        response = client.get(reverse("web:tool", kwargs={"slug": tool.slug}))

        _assert_tool_page(response)
        assert ENFORCE_HEADER not in response.headers

    def test_inactive_tool_is_not_found(self, client, tool):
        ExternalTool.objects.filter(pk=tool.pk).update(is_active=False)

        response = client.get(reverse("web:tool", kwargs={"slug": tool.slug}))

        assert_response_404(response)

    def test_unknown_tool_is_not_found(self, client):
        response = client.get(reverse("web:tool", kwargs={"slug": "no-such-tool"}))

        assert_response_404(response)
