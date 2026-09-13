"""Query bounds for the confirmations views — constant, not per facilitator.

The bounds are deliberately close to the real counts: a limit generous enough
to absorb a per-facilitator query would hide the regression it exists to catch.
"""

from http import HTTPStatus

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from ludamus.inits.middleware import SUBSCRIBED_SPHERES_SESSION_KEY
from ludamus.links.db.django.models import NotificationSubscription

# Five reads (organizers, tracks, track managers, facilitator-less items, the
# event totals) plus the panel chrome.
_DASHBOARD_QUERY_LIMIT = 21
# Five reads (facilitators of the block, their session rows, track names,
# co-facilitator names, facilitator-less items) plus the panel chrome.
_TRACK_VIEW_QUERY_LIMIT = 21


@pytest.fixture(autouse=True)
def _subscribed_session(authenticated_client, active_user, sphere):
    # The visit middleware subscribes and flags the session once per session;
    # seeding both keeps that write out of the measured requests, which must
    # stay free to catch first-request cost.
    NotificationSubscription.objects.create(
        user=active_user, sphere=sphere, source="visit"
    )
    session = authenticated_client.session
    session[SUBSCRIBED_SPHERES_SESSION_KEY] = [sphere.pk]
    session.save()


def _query_count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    # Status only -- these tests make no claim about the rendered context, so
    # assert_response would force a whole-dict wildcard that asserts nothing.
    assert response.status_code == HTTPStatus.OK, response.status_code
    return len(ctx.captured_queries)


class TestConfirmationsQueryBounds:
    def test_dashboard_bounded_queries(
        self, authenticated_client, active_user, sphere, confirmations_scale_data
    ):
        event = confirmations_scale_data["event"]
        sphere.managers.add(active_user)

        count = _query_count(
            authenticated_client,
            reverse("panel:timetable-confirmations", kwargs={"slug": event.slug}),
        )

        assert (
            count <= _DASHBOARD_QUERY_LIMIT
        ), f"Dashboard used {count} queries, expected ≤ {_DASHBOARD_QUERY_LIMIT}"

    def test_track_view_bounded_queries(
        self, authenticated_client, active_user, sphere, confirmations_scale_data
    ):
        event = confirmations_scale_data["event"]
        track = confirmations_scale_data["tracks"][0]
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})

        count = _query_count(authenticated_client, f"{url}?track={track.pk}")

        assert (
            count <= _TRACK_VIEW_QUERY_LIMIT
        ), f"Track view used {count} queries, expected ≤ {_TRACK_VIEW_QUERY_LIMIT}"

    def test_track_view_query_count_does_not_grow_with_the_data(
        self,
        authenticated_client,
        active_user,
        sphere,
        confirmations_scale_data,
        grow_confirmations_data,
    ):
        event = confirmations_scale_data["event"]
        track = confirmations_scale_data["tracks"][0]
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-confirmations", kwargs={"slug": event.slug})
        track_url = f"{url}?track={track.pk}"

        before = _query_count(authenticated_client, track_url)
        grow_confirmations_data(confirmations_scale_data)
        after = _query_count(authenticated_client, track_url)

        assert after == before

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

        before = _query_count(authenticated_client, url)
        grow_confirmations_data(confirmations_scale_data)
        after = _query_count(authenticated_client, url)

        assert after == before
