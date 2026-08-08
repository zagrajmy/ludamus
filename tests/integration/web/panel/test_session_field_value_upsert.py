from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import SessionField, SessionFieldValue
from tests.integration.utils import assert_response
from tests.integration.web.panel.test_proposal_edit_page import (
    TestProposalEditPageView,
    _make_session,
    _require_field,
)


class TestSessionFieldValueUpsertOnProposalEdit(TestProposalEditPageView):
    def test_post_twice_updates_existing_session_field_values(
        self, panel_client, event
    ):
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="18+",
            question="Is this session 18+?",
            slug="adult",
            field_type="checkbox",
            order=0,
        )
        _require_field(session, field)
        data = {
            "category_id": session.category_id,
            "title": "Updated",
            "display_name": "Host",
            "participants_limit": 5,
            "min_age": 0,
            "session_adult": "true",
        }
        url = self.get_url(event, session.pk)
        detail_url = reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        )
        first = panel_client.post(url, data=data)
        assert_response(
            first,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=detail_url,
        )
        values = SessionFieldValue.objects.filter(session=session, field=field)
        assert values.count() == 1

        data["session_adult"] = "false"
        response = panel_client.post(url, data=data)
        assert_response(
            response,
            HTTPStatus.FOUND,
            # Neither redirect is followed, so the first post's message is still
            # queued alongside the second one.
            messages=[
                (messages.SUCCESS, "Proposal updated successfully."),
                (messages.SUCCESS, "Proposal updated successfully."),
            ],
            url=detail_url,
        )
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is False
        assert values.count() == 1
