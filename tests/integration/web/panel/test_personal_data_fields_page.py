from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import PersonalDataField
from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestPersonalDataFieldsPageView:
    """Tests for /panel/event/<slug>/cfp/personal-data/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:personal-data-fields", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-fields.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "host",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "fields": [],
            },
        )

    def test_get_returns_fields_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event, name="Email", question="What is your email?", slug="email"
        )
        PersonalDataField.objects.create(
            event=event, name="Phone", question="What is your phone?", slug="phone"
        )

        response = authenticated_client.get(self.get_url(event))

        # Verify fields are FieldUsageSummary instances
        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # Email + Phone
        assert fields[0].field.name == "Email"
        assert fields[1].field.name == "Phone"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-fields.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "host",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "fields": fields,
            },
        )

    def test_get_returns_empty_list_when_no_fields(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-fields.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "host",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "fields": [],
            },
        )

    def test_get_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:personal-data-fields", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_get_returns_fields_ordered_by_order_then_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event,
            name="Phone",
            question="What is your phone?",
            slug="phone",
            order=2,
        )
        PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="What is your email?",
            slug="email",
            order=1,
        )
        PersonalDataField.objects.create(
            event=event,
            name="City",
            question="What city are you in?",
            slug="city",
            order=1,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1 + 1  # Phone + Email + City
        # Order 1 fields first (alphabetically: City, Email), then order 2 (Phone)
        assert fields[0].field.name == "City"
        assert fields[1].field.name == "Email"
        assert fields[2].field.name == "Phone"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/personal-data-fields.html",
            context_data={
                "current_event": EventDTO.model_validate(event),
                "events": [EventDTO.model_validate(event)],
                "is_proposal_active": False,
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 0,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 0,
                    "total_sessions": 0,
                },
                "active_nav": "cfp",
                "active_tab": "host",
                "tab_urls": {
                    "types": reverse("panel:cfp", kwargs={"slug": event.slug}),
                    "host": reverse(
                        "panel:personal-data-fields", kwargs={"slug": event.slug}
                    ),
                    "session": reverse(
                        "panel:session-fields", kwargs={"slug": event.slug}
                    ),
                    "time_slots": reverse(
                        "panel:time-slots", kwargs={"slug": event.slug}
                    ),
                },
                "fields": fields,
            },
        )

    def test_get_returns_field_with_is_multiple_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event,
            name="Languages",
            question="What languages do you speak?",
            slug="languages",
            field_type="select",
            is_multiple=True,
        )
        PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country are you from?",
            slug="country",
            field_type="select",
            is_multiple=False,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # Languages + Country
        # Fields should have is_multiple attribute in DTO
        country_field = next(f.field for f in fields if f.field.name == "Country")
        languages_field = next(f.field for f in fields if f.field.name == "Languages")
        assert country_field.is_multiple is False
        assert languages_field.is_multiple is True

    def test_get_returns_field_with_allow_custom_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        PersonalDataField.objects.create(
            event=event,
            name="Country",
            question="What country are you from?",
            slug="country",
            field_type="select",
            allow_custom=True,
        )
        PersonalDataField.objects.create(
            event=event,
            name="City",
            question="What city are you in?",
            slug="city",
            field_type="select",
            allow_custom=False,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # Country + City
        country_field = next(f.field for f in fields if f.field.name == "Country")
        city_field = next(f.field for f in fields if f.field.name == "City")
        assert country_field.allow_custom is True
        assert city_field.allow_custom is False
