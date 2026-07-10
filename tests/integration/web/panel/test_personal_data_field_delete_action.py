from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    PersonalDataField,
    PersonalDataFieldRequirement,
    ProposalCategory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


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

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_deletes_field_for_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )

        response = authenticated_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Personal data field deleted successfully.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert not PersonalDataField.objects.filter(pk=field.pk).exists()

    def test_post_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        url = reverse(
            "panel:personal-data-field-delete",
            kwargs={"slug": "nonexistent", "field_slug": field.slug},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_post_redirects_on_invalid_field_slug(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:personal-data-field-delete",
            kwargs={"slug": event.slug, "field_slug": "nonexistent"},
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Personal data field not found.")],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )

    def test_post_error_when_field_used_in_category(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        category = ProposalCategory.objects.create(
            event=event, name="Session", slug="session"
        )
        PersonalDataFieldRequirement.objects.create(
            field=field, category=category, is_required=True
        )

        response = authenticated_client.post(self.get_url(event, field))

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
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
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

        response = authenticated_client.post(self.get_url(event, field))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "Cannot delete field that is used in categories.")
            ],
            url=f"/panel/event/{event.slug}/cfp/personal-data/",
        )
        assert PersonalDataField.objects.filter(pk=field.pk).exists()
