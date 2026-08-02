from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    EventPanelSettings,
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
)
from ludamus.pacts.chronology import MultiselectOptionDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _facilitator(event, name, slug):
    return Facilitator.objects.create(
        event=event, display_name=name, slug=slug, user=None
    )


class TestTimetableFacilitatorOptionsPartView:
    """Tests for /panel/event/<slug>/timetable/parts/facilitator-options/."""

    @staticmethod
    def get_url(event):
        return reverse(
            "panel:timetable-facilitator-options-part", kwargs={"slug": event.slug}
        )

    @staticmethod
    def _options(response):
        return response.context["options"]

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_offers_nobody_without_a_query(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _facilitator(event, "Alice", "alice")

        response = authenticated_client.get(self.get_url(event))

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == []
        assert response.context["searched"] is False

    def test_a_search_with_no_matches_is_distinguishable_from_no_search(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _facilitator(event, "Alice", "alice")

        response = authenticated_client.get(self.get_url(event), {"q": "zzz"})

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == []
        assert response.context["searched"] is True

    def test_finds_by_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event, "Alice", "alice")
        _facilitator(event, "Bob", "bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(self.get_url(event), {"q": "ali"})

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == [
            MultiselectOptionDTO(value=alice.pk, label="Alice")
        ]

    def test_finds_by_a_text_personal_data_field(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="Email",
            question="Email?",
            slug="email",
            field_type="text",
            order=0,
        )
        alice = _facilitator(event, "Alice", "alice")
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="alice@example.com"
        )
        _facilitator(event, "Bob", "bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name", f"field_{field.pk}"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice@example.com"}
        )

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == [
            MultiselectOptionDTO(
                value=alice.pk, label="Alice", meta="Email: alice@example.com"
            )
        ]

    def test_rows_use_the_columns_configured_for_the_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        field = PersonalDataField.objects.create(
            event=event,
            name="City",
            question="City?",
            slug="city",
            field_type="text",
            order=0,
        )
        alice = _facilitator(event, "Alice", "alice")
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="Kraków"
        )
        # City first, so it names the row and the display name drops to meta.
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": [f"field_{field.pk}", "name"]}
        )

        response = authenticated_client.get(self.get_url(event), {"q": "alice"})

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == [
            MultiselectOptionDTO(
                value=alice.pk, label="Kraków", meta="Display Name: Alice"
            )
        ]

    def test_already_picked_come_back_even_when_they_do_not_match(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event, "Alice", "alice")
        bob = _facilitator(event, "Bob", "bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "bob", "facilitator": str(alice.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == [
            MultiselectOptionDTO(value=alice.pk, label="Alice"),
            MultiselectOptionDTO(value=bob.pk, label="Bob"),
        ]
        assert response.context["selected_values"] == {alice.pk}

    def test_a_picked_pk_is_never_listed_twice(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event, "Alice", "alice")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice", "facilitator": str(alice.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == [
            MultiselectOptionDTO(value=alice.pk, label="Alice")
        ]

    def test_a_facilitator_from_another_event_is_never_offered(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        foreign = _facilitator(EventFactory(sphere=sphere), "Alice", "alice")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice", "facilitator": str(foreign.pk)}
        )

        assert response.status_code == HTTPStatus.OK
        assert self._options(response) == []
