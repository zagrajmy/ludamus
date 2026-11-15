"""An event with no proposal categories asks the panel for none."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator, ProposalCategory, Session
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_proposal_not_found,
    facilitator_list_item_dto,
)
from tests.integration.web.panel.proposal_form.helpers import (
    SAVED_TITLE,
    form_page,
    form_url,
    make_session,
)


def _detail_url(event, session):
    return reverse(
        "panel:proposal-detail", kwargs={"slug": event.slug, "proposal_id": session.pk}
    )


def _create_data(event):
    facilitator = Facilitator.objects.create(
        event=event, display_name="Alice", slug="alice", user=None
    )
    return {
        "facilitators_submitted": "1",
        "facilitator_ids": [facilitator.pk],
        "title": SAVED_TITLE,
        "facilitator_name": "Test Host",
    }


class TestNoCategories:
    def test_create_saves_a_proposal_without_a_category(self, panel_client, event):
        response = panel_client.post(form_url(event), data=_create_data(event))

        session = Session.objects.get(event=event, title=SAVED_TITLE)
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=_detail_url(event, session),
        )
        assert session.category_id is None

    def test_edit_saves_a_proposal_without_a_category(self, panel_client, event):
        session = make_session(event, category=None)
        # make_session also seeds the event an RPG category; this event has none.
        ProposalCategory.objects.filter(event=event).delete()

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "title": SAVED_TITLE,
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=_detail_url(event, session),
        )
        session.refresh_from_db()
        assert (session.title, session.category_id) == (SAVED_TITLE, None)

    def test_another_events_proposal_stays_out_of_reach(self, panel_client, event):
        foreign = make_session(EventFactory(sphere=event.sphere), category=None)

        response = panel_client.post(
            form_url(event, foreign.pk),
            data={"title": SAVED_TITLE, "facilitator_name": "Test Host"},
        )

        assert_proposal_not_found(response, event)
        foreign.refresh_from_db()
        assert foreign.title != SAVED_TITLE


class TestWithCategories:
    def test_create_still_asks_for_a_category(self, panel_client, event):
        ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")

        data = _create_data(event)
        facilitator = Facilitator.objects.get(event=event, slug="alice")

        response = panel_client.post(form_url(event), data=data)

        page = form_page(event)
        page["context_data"] |= {
            "all_facilitators": [facilitator_list_item_dto(facilitator)],
            "assigned_facilitator_pks": {facilitator.pk},
        }
        assert_response(response, HTTPStatus.OK, **page)
        assert not Session.objects.filter(title=SAVED_TITLE).exists()
