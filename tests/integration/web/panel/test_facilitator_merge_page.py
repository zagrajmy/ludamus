"""Integration tests for the facilitator merge flow."""

from http import HTTPStatus
from itertools import starmap

from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.links.db.django.models import (
    AccreditationType,
    Facilitator,
    FacilitatorChangeLog,
    Guild,
    GuildMembership,
    PersonalDataField,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
)
from ludamus.pacts import FacilitatorDTO, OrganizerFieldDTO
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_not_a_manager,
    facilitator_list_item_dto,
    panel_context,
)

MULTIPLE_LINKED_ERROR = (
    "These facilitators each have a linked user account. Unlink all but one "
    "before merging."
)


def _make_facilitator(event, *, display_name, slug, **kwargs):
    return Facilitator.objects.create(
        event=event, display_name=display_name, slug=slug, user=None, **kwargs
    )


def _event_context(event):
    return {
        **panel_context(event, active_nav="facilitators"),
        "active_tab": "merge",
        "tab_urls": {
            "list": reverse("panel:facilitators", kwargs={"slug": event.slug}),
            "merge": reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
            "columns": reverse(
                "panel:facilitator-columns", kwargs={"slug": event.slug}
            ),
        },
    }


def _search_context(
    event, *, basket, search_query="", search_results=(), can_merge=False
):
    return {
        **_event_context(event),
        "confirm": False,
        "basket": [facilitator_list_item_dto(f) for f in basket],
        "search_query": search_query,
        "search_results": [facilitator_list_item_dto(f) for f in search_results],
        "can_merge": can_merge,
    }


def _accreditation_choice(value, sources, checked):
    return (
        value,
        ACCREDITATION_TYPE_LABELS[AccreditationType(value)],
        sources,
        checked,
    )


def _field_dto(field):
    return OrganizerFieldDTO(
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
    event,
    *,
    facilitators,
    name_choices,
    accreditation_choices,
    field_choices,
    error,
    unanimous_display_name=None,
    unanimous_accreditation=None,
):
    return {
        **_event_context(event),
        "confirm": True,
        "facilitators": [FacilitatorDTO.model_validate(f) for f in facilitators],
        "name_choices": name_choices,
        "unanimous_display_name": unanimous_display_name,
        "accreditation_choices": list(
            starmap(_accreditation_choice, accreditation_choices)
        ),
        "unanimous_accreditation": unanimous_accreditation,
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

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_search_results_exclude_basket(self, panel_client, event):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        nowak = _make_facilitator(event, display_name="Adam Nowak", slug="adam-nowak")
        _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        response = panel_client.get(
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

    def test_add_and_remove_adjust_the_basket(self, panel_client, event):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        added = panel_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski"], "add": "jan-wysocki"},
        )
        removed = panel_client.get(
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

    def test_stale_basket_slugs_drop_silently(self, panel_client, event):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )

        response = panel_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski", "ghost"]}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[adam]),
        )

    def test_basket_keeps_its_order_and_drops_another_events_slug(
        self, panel_client, event
    ):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")
        # Another event entirely — its facilitator must not enter this basket.
        foreign = _make_facilitator(
            EventFactory(), display_name="Ola Nowak", slug="ola-nowak"
        )

        response = panel_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["jan-wysocki", foreign.slug, "adam-kowalski"]},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[jan, adam], can_merge=True),
        )

    def test_linked_badge_renders_in_basket_and_search(self, panel_client, event):
        adam = Facilitator.objects.create(
            event=event,
            display_name="Adam Kowalski",
            slug="adam-kowalski",
            user=UserFactory(name="Adam User"),
        )
        jan = Facilitator.objects.create(
            event=event,
            display_name="Jan Wysocki",
            slug="jan-wysocki",
            user=UserFactory(name="Jan User"),
        )

        response = panel_client.get(
            self.get_url(event), {"facilitator_slugs": ["adam-kowalski"], "q": "Jan"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(
                event, basket=[adam], search_query="Jan", search_results=[jan]
            ),
            contains=["Linked"],
        )


class TestFacilitatorMergeConfirm:
    """The reconcile-then-confirm state of /facilitators/merge/."""

    @staticmethod
    def get_url(event):
        return reverse("panel:facilitator-merge", kwargs={"slug": event.slug})

    def test_confirm_offers_reconciliation_choices(self, panel_client, event):
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

        response = panel_client.get(
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
                name_choices=[("Adam Kowalski", True), ("Jan Wysocki", False)],
                accreditation_choices=[
                    ("guest", "Adam Kowalski", True),
                    ("none", "Jan Wysocki", False),
                ],
                field_choices=[
                    (
                        _field_dto(field),
                        [
                            (adam.pk, "Vegan", "Adam Kowalski", True),
                            (jan.pk, "Vegetarian", "Jan Wysocki", False),
                        ],
                    )
                ],
                error=None,
            ),
        )

    def test_confirm_asks_about_nothing_the_facilitators_agree_on(
        self, panel_client, event
    ):
        adam = _make_facilitator(event, display_name="Adam Kowalski", slug="adam-1")
        twin = _make_facilitator(event, display_name="Adam Kowalski", slug="adam-2")
        field = PersonalDataField.objects.create(
            event=event,
            name="Diet",
            question="Diet?",
            slug="diet",
            field_type="text",
            order=0,
        )
        PersonalDataFieldValue.objects.create(
            facilitator=twin, event=event, field=field, value="Vegan"
        )

        response = panel_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-1", "adam-2"], "confirm": "1"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_confirm_context(
                event,
                facilitators=[adam, twin],
                name_choices=[],
                unanimous_display_name="Adam Kowalski",
                accreditation_choices=[],
                unanimous_accreditation="none",
                field_choices=[],
                error=None,
            ),
            contains=[
                'name="display_name"',
                'value="Adam Kowalski"',
                'name="accreditation_type"',
                'value="none"',
            ],
            # The agreed answer never round-trips through the browser: the
            # merge reads it inside its own transaction.
            not_contains=["Reconcile values", f'name="personal_{field.pk}"'],
        )

    def test_post_merge_keeps_unanimous_field_value_on_target(
        self, panel_client, event
    ):
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
            facilitator=jan, event=event, field=field, value="Vegan"
        )

        response = panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "adam-kowalski",
                "display_name": "Adam Kowalski",
                "accreditation_type": "none",
                # No `personal_` input: a submission stripped of everything the
                # confirm screen didn't ask about must still keep the answer.
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        adam.refresh_from_db()
        assert not Facilitator.objects.filter(slug="jan-wysocki").exists()
        value = PersonalDataFieldValue.objects.get(facilitator=adam, field=field)
        assert value.value == "Vegan"

    def _merge_alice(self, client, event):
        return client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["alice", "alice-dup"],
                "target_slug": "alice",
                "display_name": "Alice",
                "accreditation_type": "none",
            },
        )

    def test_post_keeps_the_only_organizer_among_merged(self, panel_client, event):
        organizer = UserFactory(username="organizer", email="organizer@example.com")
        target = _make_facilitator(event, display_name="Alice", slug="alice")
        source = _make_facilitator(
            event, display_name="Alice Duplicate", slug="alice-dup"
        )
        Facilitator.objects.filter(pk=source.pk).update(organizer=organizer)

        response = self._merge_alice(panel_client, event)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.organizer_id == organizer.pk

    def test_post_keeps_the_targets_organizer_over_a_disagreeing_source(
        self, panel_client, event
    ):
        one = UserFactory(username="organizer-one", email="organizer1@example.com")
        two = UserFactory(username="organizer-two", email="organizer2@example.com")
        target = _make_facilitator(event, display_name="Alice", slug="alice")
        source = _make_facilitator(
            event, display_name="Alice Duplicate", slug="alice-dup"
        )
        Facilitator.objects.filter(pk=target.pk).update(organizer=one)
        Facilitator.objects.filter(pk=source.pk).update(organizer=two)

        response = self._merge_alice(panel_client, event)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.organizer_id == one.pk

    def test_post_clears_disagreeing_organizers_of_an_unheld_target(
        self, panel_client, event
    ):
        one = UserFactory(username="organizer-one", email="organizer1@example.com")
        two = UserFactory(username="organizer-two", email="organizer2@example.com")
        target = _make_facilitator(event, display_name="Alice", slug="alice")
        first = _make_facilitator(
            event, display_name="Alice Duplicate", slug="alice-dup"
        )
        second = _make_facilitator(event, display_name="Alice Copy", slug="alice-copy")
        Facilitator.objects.filter(pk=first.pk).update(organizer=one)
        Facilitator.objects.filter(pk=second.pk).update(organizer=two)

        response = panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["alice", "alice-dup", "alice-copy"],
                "target_slug": "alice",
                "display_name": "Alice",
                "accreditation_type": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.organizer_id is None

    def test_post_keeps_a_shared_organizer(self, panel_client, event):
        organizer = UserFactory(username="organizer", email="organizer@example.com")
        target = _make_facilitator(event, display_name="Alice", slug="alice")
        source = _make_facilitator(
            event, display_name="Alice Duplicate", slug="alice-dup"
        )
        Facilitator.objects.filter(pk__in=[target.pk, source.pk]).update(
            organizer=organizer
        )

        response = self._merge_alice(panel_client, event)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.organizer_id == organizer.pk

    def test_confirm_with_too_small_basket_falls_back_to_search(
        self, panel_client, event
    ):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )

        response = panel_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski"], "confirm": "1"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/facilitator-merge.html",
            context_data=_search_context(event, basket=[adam]),
        )

    def test_confirm_with_foreign_facilitator_is_not_found(
        self, panel_client, sphere, event
    ):
        _make_facilitator(event, display_name="Adam Kowalski", slug="adam-kowalski")
        other_event = EventFactory(sphere=sphere)
        _make_facilitator(other_event, display_name="Foreign", slug="foreign")

        response = panel_client.get(
            self.get_url(event),
            {"facilitator_slugs": ["adam-kowalski", "foreign"], "confirm": "1"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:facilitator-merge", kwargs={"slug": event.slug}),
        )

    def test_post_merges_with_reconciled_values(self, panel_client, event):
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

        response = panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "adam-kowalski",
                "display_name": "Jan Wysocki",
                "accreditation_type": "guest",
                f"personal_{field.pk}": str(jan.pk),
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

    def test_merge_records_what_it_absorbed_and_changed(
        self, panel_client, active_user, event
    ):
        # A merge deletes facilitators and rewrites the survivor's answers; the
        # change log is the only place that stays true about it afterwards.
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "adam-kowalski",
                "display_name": "Jan Wysocki",
                "accreditation_type": "guest",
            },
        )

        log = FacilitatorChangeLog.objects.get(facilitator=adam)
        assert log.user == active_user
        assert log.changes == [
            {"field": "merged_from", "field_id": None, "old": "Jan Wysocki", "new": ""},
            {
                "field": "display_name",
                "field_id": None,
                "old": "Adam Kowalski",
                "new": "Jan Wysocki",
            },
            {
                "field": "accreditation_type",
                "field_id": None,
                "old": "none",
                "new": "guest",
            },
        ]

    def test_post_rejects_a_target_outside_the_selection(self, panel_client, event):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        response = panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["adam-kowalski", "jan-wysocki"],
                "target_slug": "somebody-else",
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
                name_choices=[("Adam Kowalski", True), ("Jan Wysocki", False)],
                accreditation_choices=[],
                unanimous_accreditation="none",
                field_choices=[],
                error=(
                    "Choose which of the selected facilitators the others merge into."
                ),
            ),
        )
        assert Facilitator.objects.filter(slug="jan-wysocki").exists()

    def test_post_rejects_two_linked_users(self, panel_client, event):
        adam = _make_facilitator(
            event, display_name="Adam Kowalski", slug="adam-kowalski"
        )
        jan = _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")
        adam.user = UserFactory()
        adam.save()
        jan.user = UserFactory()
        jan.save()

        response = panel_client.post(
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
                name_choices=[("Adam Kowalski", True), ("Jan Wysocki", False)],
                accreditation_choices=[],
                unanimous_accreditation="none",
                field_choices=[],
                error=MULTIPLE_LINKED_ERROR,
            ),
        )
        assert Facilitator.objects.filter(slug="jan-wysocki").exists()

    def test_post_rejects_foreign_facilitator(self, panel_client, sphere, event):
        _make_facilitator(event, display_name="Adam Kowalski", slug="adam-kowalski")
        other_event = EventFactory(sphere=sphere)
        _make_facilitator(other_event, display_name="Foreign", slug="foreign")

        response = panel_client.post(
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

    def test_post_moves_an_accountless_targets_guild_onto_the_linked_source(
        self, panel_client, event
    ):
        guild = Guild.objects.create(sphere=event.sphere, name="Topory", slug="topory")
        target = _make_facilitator(
            event, display_name="Alice", slug="alice", guild=guild
        )
        user = UserFactory()
        _make_facilitator(event, display_name="Alice Duplicate", slug="alice-dup")
        Facilitator.objects.filter(slug="alice-dup").update(user=user)

        response = self._merge_alice(panel_client, event)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.user_id == user.pk
        assert target.guild_id is None
        assert GuildMembership.objects.filter(
            sphere=event.sphere, guild=guild, member=user
        ).exists()

    def test_post_does_not_move_an_incoming_user_into_the_targets_guild(
        self, panel_client, event
    ):
        kept = Guild.objects.create(sphere=event.sphere, name="Kept", slug="kept")
        other = Guild.objects.create(sphere=event.sphere, name="Other", slug="other")
        user = UserFactory()
        GuildMembership.objects.create(sphere=event.sphere, guild=kept, member=user)
        target = _make_facilitator(
            event, display_name="Alice", slug="alice", guild=other
        )
        _make_facilitator(event, display_name="Alice Duplicate", slug="alice-dup")
        Facilitator.objects.filter(slug="alice-dup").update(user=user)

        response = self._merge_alice(panel_client, event)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.user_id == user.pk
        assert target.guild_id is None
        assert GuildMembership.objects.filter(
            sphere=event.sphere, guild=kept, member=user
        ).exists()
        assert not GuildMembership.objects.filter(guild=other, member=user).exists()

    def test_post_does_not_move_an_incoming_users_membership_to_inherit_a_guild(
        self, panel_client, event
    ):
        kept = Guild.objects.create(sphere=event.sphere, name="Kept", slug="kept")
        other = Guild.objects.create(sphere=event.sphere, name="Other", slug="other")
        user = UserFactory()
        GuildMembership.objects.create(sphere=event.sphere, guild=kept, member=user)
        target = _make_facilitator(event, display_name="Alice", slug="alice")
        _make_facilitator(event, display_name="Alice Duplicate", slug="alice-dup")
        Facilitator.objects.filter(slug="alice-dup").update(user=user)
        _make_facilitator(
            event, display_name="Alice Copy", slug="alice-copy", guild=other
        )

        response = panel_client.post(
            self.get_url(event),
            {
                "facilitator_slugs": ["alice", "alice-dup", "alice-copy"],
                "target_slug": "alice",
                "display_name": "Alice",
                "accreditation_type": "none",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators merged successfully.")],
            url=reverse("panel:facilitators", kwargs={"slug": event.slug}),
        )
        target.refresh_from_db()
        assert target.user_id == user.pk
        assert target.guild_id is None
        assert GuildMembership.objects.filter(
            sphere=event.sphere, guild=kept, member=user
        ).exists()
        assert not GuildMembership.objects.filter(guild=other, member=user).exists()


class TestBulkMergeHandoff:
    """The list's bulk 'Merge selected' action pre-fills the basket."""

    def test_bulk_merge_redirects_to_basket(self, panel_client, event):
        _make_facilitator(event, display_name="Adam Kowalski", slug="adam-kowalski")
        _make_facilitator(event, display_name="Jan Wysocki", slug="jan-wysocki")

        response = panel_client.post(
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
