from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone

from ludamus.links.db.django.models import EventProposalSettings, Session
from ludamus.pacts import EventDTO, EventProposalSettingsDTO, SessionStatus
from tests.integration.utils import assert_response


def _url(event, step=""):
    name = f"session-propose-{step}" if step else "session-propose"
    return reverse(f"web:event:{name}", kwargs={"event_slug": event.slug})


@pytest.mark.parametrize("anonymous", (False, True))
def test_proposal_without_categories_can_be_submitted(
    client, authenticated_client, active_user, event, anonymous
):
    now = timezone.now()
    event.proposal_start_time = now - timedelta(days=1)
    event.proposal_end_time = now + timedelta(days=1)
    event.save()
    settings = EventProposalSettings.objects.create(
        event=event, allow_anonymous_proposals=True
    )
    proposer = client if anonymous else authenticated_client
    if anonymous:
        proposer.logout()
    steps = ["personal", "details", "review"] if anonymous else ["details", "review"]
    base = {
        "event": EventDTO.model_validate(event),
        "proposal_settings": EventProposalSettingsDTO.model_validate(settings),
        "wizard_steps": steps,
    }

    response = proposer.get(_url(event))
    if anonymous:
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="event/propose/base.html",
            context_data={
                **base,
                "current_step": "personal",
                "is_first_step": True,
                "form": ANY,
                "field_descriptors": [],
                "show_login_nudge": True,
                "login_url": f"/crowd/login-required/?next={_url(event)}",
                "wizard_part_template": "event/propose/parts/personal.html",
            },
        )
        response = proposer.post(
            _url(event, "personal"), {"contact_email": "host@example.com"}
        )
    assert_response(
        response,
        HTTPStatus.OK,
        template_name=(
            "event/propose/parts/details.html"
            if anonymous
            else "event/propose/base.html"
        ),
        context_data={
            **base,
            "current_step": "details",
            "is_first_step": not anonymous,
            "category": None,
            "form": ANY,
            "image_form": ANY,
            "track_options": [],
            "track_error": None,
            "public_field_descriptors": [],
            "private_field_descriptors": [],
            "reusable_sessions": [],
            "reusable_form_values": {},
            **(
                {}
                if anonymous
                else {"wizard_part_template": "event/propose/parts/details.html"}
            ),
        },
    )

    response = proposer.post(
        _url(event, "details"),
        {
            "title": "Uncategorized proposal",
            "description": "No organizer setup needed.",
            "facilitator_name": "Host",
        },
    )
    assert_response(
        response,
        HTTPStatus.OK,
        template_name="event/propose/parts/review.html",
        context_data={
            **base,
            "current_step": "review",
            "is_first_step": False,
            "category": None,
            "review": {
                "category_name": "",
                "title": "Uncategorized proposal",
                "description": "No organizer setup needed.",
                "facilitator_name": "Host",
                "participants_limit": "",
                "min_age": 0,
                "duration": "",
                "contact_email": "host@example.com" if anonymous else active_user.email,
                "public_session_fields": [],
                "private_session_fields": [],
                "public_personal_fields": [],
                "private_personal_fields": [],
                "availability": [],
            },
        },
    )
    response = proposer.post(_url(event, "submit"))
    assert_response(
        response,
        HTTPStatus.FOUND,
        url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        messages=[
            (
                messages.SUCCESS,
                "Session proposal 'Uncategorized proposal' submitted successfully!",
            )
        ],
    )
    proposal = Session.objects.get(event=event, title="Uncategorized proposal")
    assert proposal.category_id is None
    assert proposal.status == SessionStatus.PENDING
    assert proposal.participants_limit == 0
    assert list(proposal.availability.all()) == []
    assert proposal.facilitators.get().display_name == "Host"
    assert proposal.presenter_id == (None if anonymous else active_user.pk)
    assert f"propose_{event.slug}" not in proposer.session
