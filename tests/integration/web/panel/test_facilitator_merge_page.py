"""Integration tests for the facilitator merge flow."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.links.db.django.models import (
    AccreditationType,
    Facilitator,
    PersonalDataField,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
)
from ludamus.pacts import (
    EventDTO,
    FacilitatorDTO,
    FacilitatorListItemDTO,
    PersonalDataFieldDTO,
)
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."
MERGE_ERROR = (
    "These facilitators cannot be merged. Check the selection, the target, "
    "and linked accounts."
)


def _make_facilitator(event, *, display_name, slug, **kwargs):
    return Facilitator.objects.create(
        event=event, display_name=display_name, slug=slug, user=None, **kwargs
    )


def _event_context(event):
    return {
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
        "active_nav": "facilitators",
        "active_tab": "merge",
        "tab_urls": {
            "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
            "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
            "columns": reverse(
                "panel:facilitator-columns", kwargs={"slug": event.slug}
            ),
        },
    }


def _list_item(facilitator):
    return FacilitatorListItemDTO(
        accreditation_type=facilitator.accreditation_type,
        display_name=facilitator.display_name,
        pk=facilitator.pk,
        session_count=0,
        slug=facilitator.slug,
        user_id=facilitator.user_id,
    )


def _search_context(
    event, *, basket, search_query="", search_results=(), can_merge=False
):
    return {
        **_event_context(event),
        "confirm": False,
        "basket": [_list_item(f) for f in basket],
        "search_query": search_query,
        "search_results": [_list_item(f) for f in search_results],
        "can_merge": can_merge,
    }


def _accreditation_choice(value):
    return (value, ACCREDITATION_TYPE_LABELS[AccreditationType(value)])


def _field_dto(field):
    return PersonalDataFieldDTO(
        field_type=field.field_type,
        is_multiple=field.is_multiple,
        name=field.name,
        options=[],
        order=field.order,
        pk=field.pk,
        question=field.question,
        slug=field.slug,
    )


def _confirm_context(
    event, *, facilitators, name_choices, accreditation_choices, field_choices, error
):
    return {
        **_event_context(event),
        "confirm": True,
        "facilitators": [FacilitatorDTO.model_validate(f) for f in facilitators],
        "name_choices": name_choices,
        "accreditation_choices": [
            _accreditation_choice(value) for value in accreditation_choices
        ],
        "field_choices": field_choices,
        "error": error,
    }


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
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        nowak = _make_facilitator(event, display_name="Adam Nowak", slug="adam-nowak")
        _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        response = authenticated_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski"], "q": "Adam"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(
                event, basket=[adam], search_query="Adam", search_results=[nowak]
            ),
        )

    def test_add_and_remove_adjust_the_basket(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

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

        assert_response(
            added,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[adam, jan], can_merge=True),
        )
        assert_response(
            removed,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[jan]),
        )

    def test_stale_basket_slugs_drop_silently(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )

        response = authenticated_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski", "ghost"]}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[adam]),
        )


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
            event,
            display_name="Adam Kowalski",
            slug="adam-kowalski",
            accreditation_type="guest",
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")
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

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_confirm_context(
                event,
                facilitators=[adam, jan],
                name_choices=["Adam Kowalski", "Jan Wysocki"],
                accreditation_choices=["guest", "none"],
                field_choices=[(_field_dto(field), [(0, "Vegan"), (1, "Vegetarian")])],
                error=None,
            ),
        )

    def test_confirm_with_too_small_basket_falls_back_to_search(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )

        response = authenticated_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski"], "confirm": "1"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[adam]),
        )

    def test_post_merges_with_reconciled_values(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")
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
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")
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

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_confirm_context(
                event,
                facilitators=[adam, jan],
                name_choices=["Adam Kowalski", "Jan Wysocki"],
                accreditation_choices=["none"],
                field_choices=[],
                error=MERGE_ERROR,
            ),
        )
        assert Facilitator.objects.filter(slug="jan-wysocki").exists()

    def test_post_rejects_foreign_facilitator(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event, display_name="Adam Kowalski", slug="adam-kowalski")
        other_event = EventFactory(sphere=sphere)
        _make_facilitator(other_event, display_name="Foreign", slug="foreign")

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
        _make_facilitator(event, display_name="Adam Kowalski", slug="adam-kowalski")
        _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        response = authenticated_client.post(
            reverse("panel:facilitator-bulk-action", kwargs={"slug": event.slug}),
            {"action": "merge", "facilitator_slugs": ["adam-kowalski", "jan-wysocki"]},
        )

        merge_url = reverse("panel:facilitator-merge", kwargs={"slug": event.slug})
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=(
                f"{merge_url}?facilitator_slugs=adam-kowalski"
                "&facilitator_slugs=jan-wysocki"
            ),
        )
