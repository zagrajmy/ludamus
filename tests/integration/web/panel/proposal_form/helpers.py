from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    ProposalCategory,
    Session,
    SessionFieldRequirement,
)
from ludamus.pacts.legacy import SessionDTO
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    make_proposal,
    make_session_field,
    panel_context,
)

SAVED_TITLE = "Saved Session"


def form_url(event, proposal_id=None):
    if proposal_id is None:
        return reverse("panel:proposal-create", kwargs={"slug": event.slug})
    return reverse(
        "panel:proposal-edit", kwargs={"slug": event.slug, "proposal_id": proposal_id}
    )


def form_fields_url(event, proposal_id=None):
    if proposal_id is None:
        return reverse("panel:proposal-create-fields", kwargs={"slug": event.slug})
    return reverse(
        "panel:proposal-edit-fields",
        kwargs={"slug": event.slug, "proposal_id": proposal_id},
    )


def form_cancel_url(event, proposal_id=None):
    if proposal_id is None:
        return reverse("panel:proposals", kwargs={"slug": event.slug})
    return reverse(
        "panel:proposal-detail", kwargs={"slug": event.slug, "proposal_id": proposal_id}
    )


def form_context(event, session=None):
    # Everything the form renders for one pending session, or for an empty
    # create form. Tests override only the keys they care about.
    proposal_id = session.pk if session else None
    stats = (
        {"pending_proposals": 1, "total_proposals": 1, "total_sessions": 1}
        if session
        else {}
    )
    return {
        **panel_context(event, active_nav="proposals", **stats),
        "proposal": SessionDTO.model_validate(session) if session else None,
        "form": ANY,
        "cancel_url": form_cancel_url(event, proposal_id),
        "fields_url": form_fields_url(event, proposal_id),
        "field_descriptors": [],
        "orphan_values": [],
        "all_facilitators": [],
        "assigned_facilitator_pks": set(),
        "all_tracks": [],
        "assigned_track_pks": set(),
        "all_time_slots": [],
        "assigned_time_slot_pks": set(),
        "facilitator_personal_data": [],
    }


def form_page(event, session=None):
    return {
        "template_name": "panel/proposal-form.html",
        "context_data": form_context(event, session),
    }


def assert_created(response, event, *, title):
    session = Session.objects.get(event=event, title=title, status="pending")
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.SUCCESS, "Proposal created successfully.")],
        url=reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        ),
    )
    return session


def make_session(event, **kwargs):
    return make_proposal(
        event,
        **{
            "description": "A description",
            "contact_email": "host@example.com",
            "min_age": 0,
            **kwargs,
        },
    )


def saved_session(event):
    return Session.objects.get(event=event, title=SAVED_TITLE)


def require_field(session, field, *, is_required=False):
    # A session field only renders on the panel when its category asks for it.
    return SessionFieldRequirement.objects.create(
        category=session.category, field=field, is_required=is_required, order=0
    )


def category_with_field(event, *, name, slug, field_slug, is_required=False):
    category = ProposalCategory.objects.create(event=event, name=name, slug=slug)
    field = make_session_field(
        event=event,
        category=category,
        slug=field_slug,
        name=field_slug.title(),
        is_required=is_required,
    )
    return category, field
