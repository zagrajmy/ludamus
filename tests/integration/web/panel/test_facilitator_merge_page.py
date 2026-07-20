"""Integration tests for the facilitator merge flow."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
)
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
MERGE_ERROR = (
    "These facilitators cannot be merged. Check the selection, the target, "
    "and linked accounts."
)


def _make_facilitator(event, display_name, slug, **kwargs):
    return Facilitator.objects.create(
        event=event, display_name=display_name, slug=slug, user=None, **kwargs
    )


class TestFacilitatorMergeSearch:
    """The search-and-collect state of /facilitators/merge/."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-merge", kwargs={"slug": event.slug})

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

    def test_search_results_exclude_basket(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        _make_facilitator(event, "Adam Nowak", "adam-nowak")
        _make_facilitator(event, "Jan Wysocki", "jan-wysocki")

        response = authenticated_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski"], "q": "Adam"}
        )

        assert response.status_code == HTTPStatus.OK
        assert [f.slug for f in response.context["basket"]] == ["adam-kowalski"]
        assert [f.slug for f in response.context["search_results"]] == ["adam-nowak"]
        assert response.context["confirm"] is False
        assert response.context["can_merge"] is False

    def test_add_and_remove_adjust_the_basket(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        _make_facilitator(event, "Jan Wysocki", "jan-wysocki")

        added = authenticated_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski"], "add": "jan-wysocki"},
        )
        removed = authenticated_client.get(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "remove": "adam-kowalski",
            },
        )

        assert [f.slug for f in added.context["basket"]] == [
            "adam-kowalski",
            "jan-wysocki",
        ]
        assert added.context["can_merge"] is True
        assert [f.slug for f in removed.context["basket"]] == ["jan-wysocki"]

    def test_stale_basket_slugs_drop_silently(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")

        response = authenticated_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski", "ghost"]}
        )

        assert [f.slug for f in response.context["basket"]] == ["adam-kowalski"]


class TestFacilitatorMergeConfirm:
    """The reconcile-then-confirm state of /facilitators/merge/."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-merge", kwargs={"slug": event.slug})

    def test_confirm_offers_reconciliation_choices(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(
            event, "Adam Kowalski", "adam-kowalski", accreditation_type="guest"
        )
        jan = _make_facilitator(event, "Jan Wysocki", "jan-wysocki")
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Diet?",
            slug="diet",
            field_type="text",
            order=0,
        )
        PersonalDataFieldValue.objects.create(
            facilitator=adam, event=event, field=field, value="Vegan"
        )
        PersonalDataFieldValue.objects.create(
            facilitator=jan, event=event, field=field, value="Vegetarian"
        )

        response = authenticated_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski", "jan-wysocki"], "confirm": "1"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["confirm"] is True
        assert response.context["name_choices"] == ["Adam Kowalski", "Jan Wysocki"]
        assert [v for v, _label in response.context["accreditation_choices"]] == [
            "guest",
            "none",
        ]
        assert [
            (f.pk, choices) for f, choices in response.context["field_choices"]
        ] == [(field.pk, [(0, "Vegan"), (1, "Vegetarian")])]

    def test_confirm_with_too_small_basket_falls_back_to_search(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")

        response = authenticated_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski"], "confirm": "1"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["confirm"] is False

    def test_post_merges_with_reconciled_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        jan = _make_facilitator(event, "Jan Wysocki", "jan-wysocki")
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Diet?",
            slug="diet",
            field_type="text",
            order=0,
        )
        PersonalDataFieldValue.objects.create(
            facilitator=jan, event=event, field=field, value="Vegetarian"
        )
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            display_name="Jan Wysocki",
            title="Dragon Heist",
            slug="dragon-heist",
            participants_limit=5,
            status="pending",
        )
        session.facilitators.add(jan)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "adam-kowalski",
                "display_name": "Jan Wysocki",
                "accreditation_type": "guest",
                f"personal_{field.pk}": "0",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        adam.refresh_from_db()
        assert adam.display_name == "Jan Wysocki"
        assert adam.accreditation_type == "guest"
        assert not Facilitator.objects.filter(slug="jan-wysocki").exists()
        assert list(session.facilitators.all()) == [adam]
        value = PersonalDataFieldValue.objects.get(facilitator=adam, field=field)
        assert value.value == "Vegetarian"

    def test_post_rejects_two_linked_users(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        jan = _make_facilitator(event, "Jan Wysocki", "jan-wysocki")
        adam.user = UserFactory()
        adam.save()
        jan.user = UserFactory()
        jan.save()

        response = authenticated_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "adam-kowalski",
                "display_name": "Adam Kowalski",
                "accreditation_type": "none",
            },
        )

        assert response.status_code == HTTPStatus.OK
        assert response.context["error"] == MERGE_ERROR
        assert Facilitator.objects.filter(slug="jan-wysocki").exists()

    def test_post_rejects_foreign_facilitator(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        other_event = EventFactory(sphere=sphere)
        _make_facilitator(other_event, "Foreign", "foreign")

        response = authenticated_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "foreign"],
                "target_slug": "adam-kowalski",
                "display_name": "Adam Kowalski",
                "accreditation_type": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
        )
        assert Facilitator.objects.filter(slug="foreign").exists()


class TestBulkMergeHandoff:
    """The list's bulk 'Merge selected' action pre-fills the basket."""

    def test_bulk_merge_redirects_to_basket(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, "Adam Kowalski", "adam-kowalski")
        _make_facilitator(event, "Jan Wysocki", "jan-wysocki")

        response = authenticated_client.post(
            reverse("panel:facilitator-bulk-action", kwargs={"slug": event.slug}),
            {"action": "merge", "facilitator_slugs": ["adam-kowalski", "jan-wysocki"]},
        )

        merge_url = reverse("panel:facilitator-merge", kwargs={"slug": event.slug})
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == (
            f"{merge_url}?facilitator_slugs=adam-kowalski"
            "&facilitator_slugs=jan-wysocki"
        )
