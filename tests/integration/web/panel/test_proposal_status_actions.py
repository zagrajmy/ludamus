"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/<action>.

Accept, hold, reject and pending are the same view with a different target
status, so every case runs once per action.
"""

from dataclasses import dataclass

import pytest
from django.urls import reverse

from tests.integration.conftest import EventFactory
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    assert_proposal_not_found,
    assert_proposal_status_applied,
    assert_proposal_status_unchanged,
    assert_scheduled_proposal_refused,
    make_proposal,
    make_scheduled_proposal,
)


@dataclass(frozen=True)
class StatusAction:
    name: str
    url_name: str
    message: str
    target_status: str
    start_status: str
    alternate_start: str


ACCEPT = StatusAction(
    name="accept",
    url_name="panel:proposal-accept",
    message="Proposal accepted.",
    target_status="accepted",
    start_status="pending",
    alternate_start="on_hold",
)
HOLD = StatusAction(
    name="hold",
    url_name="panel:proposal-hold",
    message="Proposal put on hold.",
    target_status="on_hold",
    start_status="pending",
    alternate_start="accepted",
)
REJECT = StatusAction(
    name="reject",
    url_name="panel:proposal-reject",
    message="Proposal rejected.",
    target_status="rejected",
    start_status="pending",
    alternate_start="on_hold",
)
PENDING = StatusAction(
    name="pending",
    url_name="panel:proposal-pending",
    message="Proposal moved back to pending.",
    target_status="pending",
    start_status="on_hold",
    alternate_start="rejected",
)

# Accepting is the one status change a scheduled session still allows: the
# others would strand it on the timetable.
REFUSE_SCHEDULED = [HOLD, REJECT, PENDING]


def _url(event, proposal_id, action):
    return reverse(
        action.url_name, kwargs={"slug": event.slug, "proposal_id": proposal_id}
    )


@pytest.fixture(params=[ACCEPT, HOLD, REJECT, PENDING], ids=lambda a: a.name)
def action(request):
    return request.param


class TestProposalStatusActionView:
    def test_post_redirects_anonymous_user_to_login(self, client, event, action):
        session = make_proposal(event, status=action.start_status)
        url = _url(event, session.pk, action)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event, action):
        session = make_proposal(event, status=action.start_status)

        response = authenticated_client.post(_url(event, session.pk, action))

        assert_not_a_manager(response)

    def test_post_applies_the_status_and_redirects(self, panel_client, event, action):
        session = make_proposal(event, status=action.start_status)

        response = panel_client.post(_url(event, session.pk, action))

        assert_proposal_status_applied(
            response,
            event,
            session,
            message=action.message,
            status=action.target_status,
        )

    def test_post_applies_the_status_from_the_other_starting_status(
        self, panel_client, event, action
    ):
        session = make_proposal(event, status=action.alternate_start)

        response = panel_client.post(_url(event, session.pk, action))

        assert_proposal_status_applied(
            response,
            event,
            session,
            message=action.message,
            status=action.target_status,
        )

    def test_post_redirects_when_event_not_found(self, panel_client, action):
        url = reverse(action.url_name, kwargs={"slug": "nonexistent", "proposal_id": 1})

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_post_redirects_when_proposal_not_found(self, panel_client, event, action):
        url = _url(event, 99999, action)

        response = panel_client.post(url)

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event, action
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_proposal(other_event, status=action.start_status)

        response = panel_client.post(_url(event, session.pk, action))

        assert_proposal_not_found(response, event)
        assert_proposal_status_unchanged(session, action.start_status)


class TestScheduledProposal:
    def test_post_accepts_a_scheduled_proposal(self, panel_client, event):
        session = make_scheduled_proposal(event)

        response = panel_client.post(_url(event, session.pk, ACCEPT))

        assert_proposal_status_applied(
            response, event, session, message=ACCEPT.message, status="accepted"
        )

    @pytest.mark.parametrize("action", REFUSE_SCHEDULED, ids=lambda a: a.name)
    def test_post_refuses_to_move_a_scheduled_proposal(
        self, panel_client, event, action
    ):
        session = make_scheduled_proposal(event)

        response = panel_client.post(_url(event, session.pk, action))

        assert_scheduled_proposal_refused(response, event, session)
        assert_proposal_status_unchanged(session, "accepted")
