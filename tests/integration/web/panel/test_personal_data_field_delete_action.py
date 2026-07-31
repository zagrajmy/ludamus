from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    PersonalDataField,
    PersonalDataFieldRequirement,
    ProposalCategory,
)
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
)


class TestPersonalDataFieldDeleteActionView:
    """Tests for /panel/event/<slug>/cfp/personal-data/<field_slug>/do/delete action."""

    @staticmethod
    def get_url(event, field):
        return reverse(
            "panel:personal-data-field-delete",
            kwargs={"slug": event.slug, "field_slug": field.slug},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = self.get_url(event, field)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(self.get_url(event, field))

        assert_not_a_manager(response)

    def test_post_deletes_field_for_manager(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = panel_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field deleted successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert not PersonalDataField.objects.filter(pk=field.pk).exists()

    def test_post_redirects_on_invalid_event_slug(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-delete",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_post_redirects_on_invalid_field_slug(self, panel_client, event):
        url = reverse(
            "panel:personal-data-field-delete",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = panel_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Personal data field not found.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )

    def test_post_error_when_field_used_in_category(self, panel_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        category = ProposalCategory.objects.create(
            event=event, name="Session", slug="session"
        )
        PersonalDataFieldRequirement.objects.create(
            field=field, category=category, is_required=True
        )

        response = panel_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete field that is used in categories.")
            ],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert PersonalDataField.objects.filter(pk=field.pk).exists()

    def test_post_error_when_field_used_in_multiple_categories(
        self, panel_client, event
    ):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        category1 = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        category2 = ProposalCategory.objects.create(
            event=event, name="Workshop", slug="workshop"
        )
        PersonalDataFieldRequirement.objects.create(
            field=field, category=category1, is_required=True
        )
        PersonalDataFieldRequirement.objects.create(
            field=field, category=category2, is_required=False
        )

        response = panel_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete field that is used in categories.")
            ],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert PersonalDataField.objects.filter(pk=field.pk).exists()
