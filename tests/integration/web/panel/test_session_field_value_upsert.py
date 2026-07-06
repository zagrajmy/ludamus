from http import HTTPStatus

from ludamus.adapters.db.django.models import (
    SessionField,
    SessionFieldRequirement,
    SessionFieldValue,
)
from tests.integration.web.panel.test_proposal_edit_page import (
    TestProposalEditPageView,
    _make_session,
)


class TestSessionFieldValueUpsertOnProposalEdit(TestProposalEditPageView):
    def test_post_twice_updates_existing_session_field_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="18+",
            question="Is this session 18+?",
            slug="adult",
            field_type="checkbox",
            order=0,
        )
        SessionFieldRequirement.objects.create(
            category=session.category, field=field, is_required=False, order=0
        )
        data = {
            "category_id": session.category_id,
            "title": "Updated",
            "display_name": "Host",
            "participants_limit": 5,
            "min_age": 0,
            "session_fields_submitted": "1",
            "session_field_adult": "true",
        }
        url = self.get_url(event, session.pk)
        first = authenticated_client.post(url, data=data)
        assert first.status_code == HTTPStatus.FOUND
        values = SessionFieldValue.objects.filter(session=session, field=field)
        assert values.count() == 1

        data["session_field_adult"] = "false"
        response = authenticated_client.post(url, data=data)
        assert response.status_code == HTTPStatus.FOUND, response.content[:500]
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is False
        assert values.count() == 1
