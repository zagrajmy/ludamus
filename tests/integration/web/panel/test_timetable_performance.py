"""Performance tests for timetable views — bounded query counts at scale.

The bounds are deliberately close to the real counts. Conflict detection and
preferred-slot attribution both used to run one query per scheduled item, and
the overview's block progress one per track; at this fixture's size that lands
in the hundreds. A limit generous enough to absorb it hides the regression it
exists to catch.
"""

from http import HTTPStatus

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.integration.web.panel.conftest import SCALE_SCHEDULED

_PAGE_QUERY_LIMIT = 45
_GRID_QUERY_LIMIT = 30
_CONFLICT_QUERY_LIMIT = 30
_OVERVIEW_QUERY_LIMIT = 40


def _query_count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == HTTPStatus.OK, response.status_code
    return len(ctx.captured_queries)


class TestTimetableQueryBounds:
    def test_timetable_page_bounded_queries(
        self, authenticated_client, active_user, sphere, timetable_scale_data
    ):
        event = timetable_scale_data["event"]
        sphere.managers.add(active_user)

        count = _query_count(
            authenticated_client,
            reverse("panel:timetable", kwargs={"slug": event.slug}),
        )

        assert count <= _PAGE_QUERY_LIMIT, (
            f"Timetable page used {count} queries for {SCALE_SCHEDULED} scheduled "
            f"items, expected ≤ {_PAGE_QUERY_LIMIT}"
        )

    def test_timetable_grid_bounded_queries(
        self, authenticated_client, active_user, sphere, timetable_scale_data
    ):
        event = timetable_scale_data["event"]
        sphere.managers.add(active_user)

        count = _query_count(
            authenticated_client,
            reverse("panel:timetable-grid-part", kwargs={"slug": event.slug}),
        )

        assert (
            count <= _GRID_QUERY_LIMIT
        ), f"Grid used {count} queries, expected ≤ {_GRID_QUERY_LIMIT}"

    def test_conflict_detection_bounded_queries(
        self, authenticated_client, active_user, sphere, timetable_scale_data
    ):
        event = timetable_scale_data["event"]
        sphere.managers.add(active_user)

        count = _query_count(
            authenticated_client,
            reverse("panel:timetable-conflicts-part", kwargs={"slug": event.slug}),
        )

        assert count <= _CONFLICT_QUERY_LIMIT, (
            f"Conflict detection used {count} queries, "
            f"expected ≤ {_CONFLICT_QUERY_LIMIT}"
        )

    def test_overview_bounded_queries(
        self, authenticated_client, active_user, sphere, timetable_scale_data
    ):
        """Overview page should not double-run conflict detection."""
        event = timetable_scale_data["event"]
        sphere.managers.add(active_user)

        count = _query_count(
            authenticated_client,
            reverse("panel:timetable-overview", kwargs={"slug": event.slug}),
        )

        assert (
            count <= _OVERVIEW_QUERY_LIMIT
        ), f"Overview used {count} queries, expected ≤ {_OVERVIEW_QUERY_LIMIT}"
