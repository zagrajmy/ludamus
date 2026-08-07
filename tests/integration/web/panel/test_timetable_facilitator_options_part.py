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
TEMPLATE = "components/multiselect-filter-options.html"


def _facilitator(*, event, name, slug):
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

    def expected_context(
        self, *, event, options, searched, selected_values=frozenset(), has_more=False
    ):
        return {
            "options": options,
            "has_more": has_more,
            "searched": searched,
            "name": "facilitator",
            "selected_values": set(selected_values),
            "search_url": self.get_url(event),
        }

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

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:timetable-facilitator-options-part", kwargs={"slug": "nonexistent"}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_offers_nobody_without_a_query(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _facilitator(event=event, name="Alice", slug="alice")

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(event=event, options=[], searched=False),
        )

    def test_a_search_with_no_matches_is_distinguishable_from_no_search(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _facilitator(event=event, name="Alice", slug="alice")

        response = authenticated_client.get(self.get_url(event), {"q": "zzz"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(event=event, options=[], searched=True),
        )

    def test_finds_by_display_name(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event=event, name="Alice", slug="alice")
        _facilitator(event=event, name="Bob", slug="bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(self.get_url(event), {"q": "ali"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[MultiselectOptionDTO(value=alice.pk, label="Alice")],
                searched=True,
            ),
        )

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
        alice = _facilitator(event=event, name="Alice", slug="alice")
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="alice@example.com"
        )
        _facilitator(event=event, name="Bob", slug="bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name", f"field_{field.pk}"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice@example.com"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[
                    MultiselectOptionDTO(
                        value=alice.pk, label="Alice", meta="Email: alice@example.com"
                    )
                ],
                searched=True,
            ),
        )

    def test_rows_are_named_by_the_person_whatever_column_comes_first(
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
        alice = _facilitator(event=event, name="Alice", slug="alice")
        PersonalDataFieldValue.objects.create(
            facilitator=alice, event=event, field=field, value="Kraków"
        )
        # City first: the organizer is free to order the list's columns however
        # they like, and the picker still has to name people by their name.
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": [f"field_{field.pk}", "name"]}
        )

        response = authenticated_client.get(self.get_url(event), {"q": "alice"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[
                    MultiselectOptionDTO(
                        value=alice.pk, label="Alice", meta="City: Kraków"
                    )
                ],
                searched=True,
            ),
        )

    def test_already_picked_come_back_even_when_they_do_not_match(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event=event, name="Alice", slug="alice")
        bob = _facilitator(event=event, name="Bob", slug="bob")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "bob", "facilitator": str(alice.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[
                    MultiselectOptionDTO(value=alice.pk, label="Alice"),
                    MultiselectOptionDTO(value=bob.pk, label="Bob"),
                ],
                searched=True,
                selected_values={alice.pk},
            ),
        )

    def test_a_picked_pk_is_never_listed_twice(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        alice = _facilitator(event=event, name="Alice", slug="alice")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice", "facilitator": str(alice.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[MultiselectOptionDTO(value=alice.pk, label="Alice")],
                searched=True,
                selected_values={alice.pk},
            ),
        )

    def test_a_facilitator_from_another_event_is_never_offered(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        foreign = _facilitator(
            event=EventFactory(sphere=sphere), name="Alice", slug="alice"
        )
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(
            self.get_url(event), {"q": "alice", "facilitator": str(foreign.pk)}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event, options=[], searched=True, selected_values={foreign.pk}
            ),
        )

    def test_more_matches_than_fit_are_flagged(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        # One past the picker's limit, so the tail marker turns on.
        for index in range(26):
            _facilitator(event=event, name=f"Ala {index:02d}", slug=f"ala-{index}")
        EventPanelSettings.objects.update_or_create(
            event=event, defaults={"facilitator_columns": ["name"]}
        )

        response = authenticated_client.get(self.get_url(event), {"q": "Ala"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=self.expected_context(
                event=event,
                options=[
                    MultiselectOptionDTO(value=f.pk, label=f.display_name)
                    for f in Facilitator.objects.order_by("display_name")[:25]
                ],
                searched=True,
                has_more=True,
            ),
        )
