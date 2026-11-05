from dataclasses import dataclass

import pytest

from ludamus.links.db.django.models import Facilitator, ProposalCategory, Session
from tests.integration.web.panel.proposal_form.helpers import (
    SAVED_TITLE,
    form_fields_url,
    form_url,
    make_session,
)


@dataclass(frozen=True)
class FormMode:
    url: str
    fields_url: str
    session: Session | None


@pytest.fixture(name="form_mode", params=("create", "edit"))
def form_mode_fixture(request, event):
    if request.param == "create":
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        return FormMode(
            url=form_url(event), fields_url=form_fields_url(event), session=None
        )
    session = make_session(event)
    return FormMode(
        url=form_url(event, session.pk),
        fields_url=form_fields_url(event, session.pk),
        session=session,
    )


@pytest.fixture(name="valid_post")
def valid_post_fixture(event, form_mode):
    data = {
        "category_id": ProposalCategory.objects.get(event=event, slug="rpg").pk,
        "title": SAVED_TITLE,
        "facilitator_name": "Test Host",
    }
    if form_mode.session:
        return data | {"participants_limit": 5, "min_age": 0}
    facilitator = Facilitator.objects.create(
        event=event, display_name="Alice", slug="alice", user=None
    )
    return data | {"facilitators_submitted": "1", "facilitator_ids": [facilitator.pk]}
