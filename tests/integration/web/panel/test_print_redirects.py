from http import HTTPStatus

import pytest
from django.urls import reverse

from tests.integration.utils import assert_response


@pytest.mark.parametrize(
    ("route_name", "query", "expected_query"),
    (
        ("panel:print-materials", "?scope=42", "?scope=42"),
        (
            "panel:timetable-print",
            "?scope=42&start=2027-04-26T10%3A00",
            "?scope=42&start=2027-04-26T10%3A00&material=timetable",
        ),
        (
            "panel:timetable-print-door-cards",
            "?hours=6",
            "?hours=6&material=door-cards",
        ),
    ),
)
def test_legacy_print_url_redirects_to_canonical_page(
    client, event, route_name, query, expected_query
):
    url = reverse(route_name, kwargs={"slug": event.slug})
    canonical_url = reverse("web:chronology:event-print", kwargs={"slug": event.slug})

    response = client.get(f"{url}{query}")

    assert_response(response, HTTPStatus.FOUND, url=f"{canonical_url}{expected_query}")
