"""Query bounds for the confirmations views — constant, not per facilitator."""

from http import HTTPStatus

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

# Four reads (organizers, tracks, track managers, facilitator-less items) plus
# the panel chrome. The point of the test is that this does not grow with the
# number of facilitators, sessions or tracks.
_DASHBOARD_QUERY_LIMIT = 25


class TestConfirmationsQueryBounds:
    def test_dashboard_bounded_queries(
        self, authenticated_client, active_user, sphere, confirmations_scale_data
    ):
        event = confirmations_scale_data["event"]
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})

        with CaptureQueriesContext(connection) as ctx:
            response = authenticated_client.get(url)

        assert response.status_code == HTTPStatus.OK
        count = len(ctx.captured_queries)
        assert (
            count <= _DASHBOARD_QUERY_LIMIT
        ), f"Dashboard used {count} queries, expected ≤ {_DASHBOARD_QUERY_LIMIT}"

    def test_dashboard_query_count_does_not_grow_with_the_data(
        self,
        authenticated_client,
        active_user,
        sphere,
        confirmations_scale_data,
        grow_confirmations_data,
    ):
        event = confirmations_scale_data["event"]
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})

        with CaptureQueriesContext(connection) as before:
            authenticated_client.get(url)
        grow_confirmations_data(confirmations_scale_data)
        with CaptureQueriesContext(connection) as after:
            response = authenticated_client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert len(after.captured_queries) == len(before.captured_queries)
