"""The three visibility choices on the event settings form, end to end."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.utils import timezone
from django.utils.timezone import localtime

from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import settings_post_data, settings_url


def _saved(response, event):
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.SUCCESS, "Event settings saved successfully.")],
        url=f"/panel/event/{event.slug}/settings/",
    )
    event.refresh_from_db()
    return event


class TestEventPublication:
    def test_makes_the_event_unlisted(self, panel_client, event):
        response = panel_client.post(
            settings_url(event), data=settings_post_data(event, publication="link_only")
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Event settings saved successfully.")],
            url=f"/panel/event/{event.slug}/settings/",
        )
        event.refresh_from_db()
        assert event.visibility == "unlisted"

    def test_public_now_publishes_a_hidden_event(self, panel_client, event):
        event.publication_time = None
        event.save()
        before = timezone.now()

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(event, publication="public_now"),
        )

        event = _saved(response, event)
        assert event.visibility == "public"
        assert before <= event.publication_time <= timezone.now()

    def test_public_now_keeps_a_past_publication_time(self, panel_client, event):
        published = timezone.now() - timedelta(days=3)
        event.publication_time = published
        event.save()

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(event, publication="public_now"),
        )

        assert _saved(response, event).publication_time == published

    def test_public_now_on_a_started_event_publishes_it_from_its_start(
        self, panel_client, event
    ):
        start = (timezone.now() - timedelta(hours=2)).replace(second=0, microsecond=0)
        event.start_time = start
        event.end_time = start + timedelta(hours=8)
        event.publication_time = None
        event.save()

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(event, publication="public_now"),
        )

        event = _saved(response, event)
        assert event.publication_time == event.start_time

    @pytest.mark.parametrize("publication", ("link_only", "public_now"))
    def test_moving_the_start_before_a_kept_publication_time_still_saves(
        self, panel_client, event, publication
    ):
        published = timezone.now() - timedelta(days=1)
        event.publication_time = published
        event.save()
        earlier_start = published - timedelta(days=2)

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(
                event,
                publication=publication,
                start_time=localtime(earlier_start).strftime("%Y-%m-%dT%H:%M"),
                end_time=localtime(earlier_start + timedelta(hours=8)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
            ),
        )

        event = _saved(response, event)
        assert event.publication_time == event.start_time

    def test_publish_at_sets_the_chosen_time(self, panel_client, event):
        when = localtime(event.start_time - timedelta(days=1)).replace(
            second=0, microsecond=0
        )

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(
                event,
                publication="scheduled",
                publication_time=when.strftime("%Y-%m-%dT%H:%M"),
            ),
        )

        event = _saved(response, event)
        assert (event.visibility, event.publication_time) == ("public", when)

    def test_publish_at_without_a_time_keeps_the_event_hidden(
        self, panel_client, event
    ):
        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(
                event, publication="scheduled", publication_time=""
            ),
        )

        event = _saved(response, event)
        assert (event.visibility, event.publication_time) == ("public", None)

    def test_link_only_keeps_the_stored_publication_time(self, panel_client, event):
        stored = event.publication_time

        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(
                event, publication="link_only", publication_time=""
            ),
        )

        event = _saved(response, event)
        assert (event.visibility, event.publication_time) == ("unlisted", stored)

    @pytest.mark.parametrize(
        ("publication", "visibility"),
        (("link_only", "unlisted"), ("public_now", "public")),
    )
    def test_a_hidden_unreadable_time_does_not_block_another_choice(
        self, panel_client, event, publication, visibility
    ):
        response = panel_client.post(
            settings_url(event),
            data=settings_post_data(
                event, publication=publication, publication_time="not a date"
            ),
        )

        assert _saved(response, event).visibility == visibility
