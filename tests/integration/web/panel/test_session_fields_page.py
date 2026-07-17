from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import SessionField
from ludamus.pacts import EventDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestSessionFieldsPageView:
    """Tests for /panel/event/<slug>/cfp/session-fields/ page."""

    @staticmethod
    def get_url(event):
        return reverse("panel:session-fields", kwargs={"slug": event.slug})

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
            template_name="panel/session-fields.html",
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
                "active_tab": "session",
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
        assert response.context["current_event"].pk == event.pk

    def test_get_returns_fields_in_context(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system will you use?",
            slug="rpg-system",
        )
        SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre"
        )

        response = authenticated_client.get(self.get_url(event))

        # Verify fields are FieldUsageSummary instances
        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # RPG System + Genre
        assert fields[0].field.name == "Genre"  # Alphabetically first
        assert fields[1].field.name == "RPG System"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/session-fields.html",
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
                "active_tab": "session",
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
            template_name="panel/session-fields.html",
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
                "active_tab": "session",
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
        url = reverse("panel:session-fields", kwargs={"slug": "nonexistent"})

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
        SessionField.objects.create(
            event=event, name="Genre", question="What genre?", slug="genre", order=2
        )
        SessionField.objects.create(
            event=event,
            name="RPG System",
            question="What RPG system will you use?",
            slug="rpg-system",
            order=1,
        )
        SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
            order=1,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1 + 1  # Genre + RPG System + Difficulty
        # Order 1 first (Difficulty, RPG System alphabetically), then order 2 (Genre)
        assert fields[0].field.name == "Difficulty"
        assert fields[1].field.name == "RPG System"
        assert fields[2].field.name == "Genre"
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/session-fields.html",
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
                "active_tab": "session",
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
        SessionField.objects.create(
            event=event,
            name="Tags",
            question="What tags apply?",
            slug="tags",
            field_type="select",
            is_multiple=True,
        )
        SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
            field_type="select",
            is_multiple=False,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # Tags + Difficulty
        # Fields should have is_multiple attribute in DTO
        difficulty_field = next(f.field for f in fields if f.field.name == "Difficulty")
        tags_field = next(f.field for f in fields if f.field.name == "Tags")
        assert difficulty_field.is_multiple is False
        assert tags_field.is_multiple is True

    def test_get_returns_field_with_allow_custom_attribute(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        SessionField.objects.create(
            event=event,
            name="Genre",
            question="What genre?",
            slug="genre",
            field_type="select",
            allow_custom=True,
        )
        SessionField.objects.create(
            event=event,
            name="Difficulty",
            question="What difficulty level?",
            slug="difficulty",
            field_type="select",
            allow_custom=False,
        )

        response = authenticated_client.get(self.get_url(event))

        fields = response.context["fields"]
        assert len(fields) == 1 + 1  # Genre + Difficulty
        genre_field = next(f.field for f in fields if f.field.name == "Genre")
        difficulty_field = next(f.field for f in fields if f.field.name == "Difficulty")
        assert genre_field.allow_custom is True
        assert difficulty_field.allow_custom is False
