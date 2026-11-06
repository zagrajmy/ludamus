"""Session field answers on the proposal form."""

from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.gates.web.django.chronology.panel.views.proposal_edit import (
    OrphanFieldValue,
)
from ludamus.links.db.django.models import (
    ContentChangeLog,
    Facilitator,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    SessionFieldValue,
)
from ludamus.pacts.fields import FieldAnswer, OrganizerFieldDTO
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    facilitator_list_item_dto,
    make_session_field,
)
from tests.integration.web.panel.proposal_form.helpers import (
    category_with_field,
    form_context,
    form_url,
    make_session,
    require_field,
    saved_session,
)


class TestBothModes:
    def test_post_stores_no_row_for_a_field_left_blank(
        self, panel_client, event, form_mode, valid_post
    ):
        field = make_session_field(
            event=event,
            category=ProposalCategory.objects.get(pk=valid_post["category_id"]),
        )

        panel_client.post(form_mode.url, data=valid_post | {"session_system": "   "})

        assert not SessionFieldValue.objects.filter(
            session=saved_session(event), field=field
        ).exists()


class TestCreate:
    def test_get_renders_only_the_resolved_categorys_fields(self, panel_client, event):
        _category, field = category_with_field(
            event, name="A", slug="a", field_slug="only-a"
        )
        category_with_field(event, name="B", slug="b", field_slug="only-b")

        response = panel_client.get(form_url(event))

        # Category A is the event's first category, so only its field renders.
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            field_type="text",
                            name=field.name,
                            options=[],
                            order=0,
                            pk=field.pk,
                            question=field.question,
                            slug=field.slug,
                        ),
                        "name_prefix": "session",
                        "answer": FieldAnswer(),
                    }
                ],
            },
        )

    def test_get_renders_checkbox_field_with_allow_custom_without_companion(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="A", slug="a")
        field = SessionField.objects.create(
            event=event,
            name="Streamed",
            question="Stream this session?",
            slug="streamed",
            field_type="checkbox",
            allow_custom=True,
            order=0,
        )
        SessionFieldRequirement.objects.create(
            category=category, field=field, is_required=False, order=0
        )

        response = panel_client.get(form_url(event))

        html = response.content.decode()
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            allow_custom=True,
                            field_type="checkbox",
                            name=field.name,
                            options=[],
                            order=0,
                            pk=field.pk,
                            question=field.question,
                            slug=field.slug,
                        ),
                        "name_prefix": "session",
                        "answer": FieldAnswer(),
                    }
                ],
            },
        )
        assert 'name="session_streamed"' in html
        assert 'name="session_streamed_custom"' not in html

    def test_post_saves_the_categorys_field_values(self, panel_client, event):
        category, field = category_with_field(
            event, name="RPG", slug="rpg", field_slug="system"
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Saved Fields",
                "facilitator_name": "Test Host",
                "session_system": "Pathfinder",
            },
        )

        session = Session.objects.get(title="Saved Fields")
        value = SessionFieldValue.objects.get(session=session, field=field)
        assert value.value == "Pathfinder"

    def test_post_rejects_missing_required_field(self, panel_client, event):
        category, field = category_with_field(
            event, name="RPG", slug="rpg", field_slug="system", is_required=True
        )
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Missing Required",
                "facilitator_name": "Test Host",
                "session_system": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            field_type="text",
                            name=field.name,
                            options=[],
                            order=0,
                            pk=field.pk,
                            question=field.question,
                            slug=field.slug,
                        ),
                        "name_prefix": "session",
                        "answer": FieldAnswer(
                            value="",
                            errors=["This field is required."],
                            is_required=True,
                        ),
                    }
                ],
            },
        )
        assert "session_system" in response.context["form"].errors
        assert not Session.objects.filter(title="Missing Required").exists()


class TestEdit:
    def test_post_saves_checkbox_session_field(self, panel_client, event):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="18+",
            question="Is this session 18+?",
            slug="adult",
            field_type="checkbox",
            order=0,
        )
        require_field(session, field)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_adult": "true",
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is True

    def test_post_blanking_an_answered_field_keeps_the_row_empty(
        self, panel_client, event
    ):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )
        require_field(session, field)
        SessionFieldValue.objects.create(
            session=session, field=field, value="Pathfinder"
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "",
            },
        )

        # The row survives as an explicit empty answer, so a later import
        # treats the field as answered and will not refill it.
        assert list(
            SessionFieldValue.objects.filter(session=session, field=field).values_list(
                "value", flat=True
            )
        ) == [""]

    def test_post_saves_multiple_session_field(self, panel_client, event):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="Genres",
            question="Which genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        for order, value in enumerate(["horror", "comedy"]):
            SessionFieldOption.objects.create(
                field=field, label=value.title(), value=value, order=order
            )
        require_field(session, field)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_genres": ["horror", "comedy"],
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == ["horror", "comedy"]

    def test_post_saves_allow_custom_session_field_from_custom_input(
        self, panel_client, event
    ):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="text",
            allow_custom=True,
            order=0,
        )
        require_field(session, field)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "",
                "session_system_custom": "Homebrew",
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == "Homebrew"

    def test_get_renders_all_session_field_types(self, panel_client, event):
        session = make_session(event)

        genres = SessionField.objects.create(
            event=event,
            name="Genres",
            question="Which genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
            help_text="Pick all that apply",
            order=0,
        )
        SessionFieldOption.objects.create(
            field=genres, label="Horror", value="horror", order=0
        )
        SessionFieldOption.objects.create(
            field=genres, label="Comedy", value="comedy", order=1
        )

        system = SessionField.objects.create(
            event=event,
            name="System",
            question="Which RPG system?",
            slug="system",
            field_type="select",
            allow_custom=True,
            order=1,
        )
        SessionFieldOption.objects.create(
            field=system, label="D&D", value="dnd", order=0
        )

        adult = SessionField.objects.create(
            event=event,
            name="18+",
            question="Adult content?",
            slug="adult",
            field_type="checkbox",
            order=2,
        )

        notes = SessionField.objects.create(
            event=event,
            name="Notes",
            question="Anything else?",
            slug="notes",
            field_type="text",
            allow_custom=True,
            max_length=99,
            help_text="Free text",
            order=3,
        )

        for field in (genres, system, adult, notes):
            require_field(session, field)

        SessionFieldValue.objects.create(
            session=session, field=genres, value=["horror"]
        )
        SessionFieldValue.objects.create(session=session, field=system, value="dnd")
        SessionFieldValue.objects.create(session=session, field=adult, value=True)
        SessionFieldValue.objects.create(
            session=session, field=notes, value="Bring dice"
        )

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                # Holds the form's BoundFields, so it can't be compared by value.
                "field_descriptors": ANY,
            },
            contains=[
                'name="session_genres"',
                "Pick all that apply",
                'name="session_system"',
                'name="session_system_custom"',
                'name="session_adult"',
                'name="session_notes"',
                'maxlength="99"',
                'name="session_notes_custom"',
            ],
        )

    def test_partial_post_without_session_fields_marker_preserves_field_values(
        self, panel_client, event
    ):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )
        SessionFieldValue.objects.create(
            session=session, field=field, value="Pathfinder"
        )

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated title only",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value == "Pathfinder"
        session.refresh_from_db()
        assert session.title == "Updated title only"

    def test_post_twice_updates_existing_session_field_values(
        self, panel_client, event
    ):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="18+",
            question="Is this session 18+?",
            slug="adult",
            field_type="checkbox",
            order=0,
        )
        require_field(session, field)
        data = {
            "category_id": session.category_id,
            "title": "Updated",
            "facilitator_name": "Host",
            "participants_limit": 5,
            "min_age": 0,
            "session_adult": "true",
        }
        url = form_url(event, session.pk)
        detail_url = reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        )
        first = panel_client.post(url, data=data)
        assert_response(
            first,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=detail_url,
        )
        values = SessionFieldValue.objects.filter(session=session, field=field)
        assert values.count() == 1

        data["session_adult"] = "false"
        response = panel_client.post(url, data=data)
        assert_response(
            response,
            HTTPStatus.FOUND,
            # Neither redirect is followed, so the first post's message is still
            # queued alongside the second one.
            messages=[
                (messages.SUCCESS, "Proposal updated successfully."),
                (messages.SUCCESS, "Proposal updated successfully."),
            ],
            url=detail_url,
        )
        sfv = SessionFieldValue.objects.get(session=session, field=field)
        assert sfv.value is False
        assert values.count() == 1


class TestEditOrphanValues:
    """Answers outside the session's category: shown apart, removable only."""

    @staticmethod
    def _orphan_setup(event):
        # `kept` is asked for by the category; `dropped` only has a stored
        # answer, so it is an orphan.
        session = make_session(event)
        kept = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )
        require_field(session, kept)
        dropped = SessionField.objects.create(
            event=event,
            name="Legacy",
            question="Legacy question?",
            slug="legacy",
            field_type="text",
            order=1,
        )
        SessionFieldValue.objects.create(
            session=session, field=dropped, value="Old answer"
        )
        return session, kept, dropped

    def test_get_lists_orphan_value_without_an_input(self, panel_client, event):
        session, kept, dropped = self._orphan_setup(event)

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "field_descriptors": [
                    {
                        "field": OrganizerFieldDTO(
                            field_type="text",
                            name=kept.name,
                            options=[],
                            order=0,
                            pk=kept.pk,
                            question=kept.question,
                            slug=kept.slug,
                        ),
                        "name_prefix": "session",
                        "answer": FieldAnswer(),
                    }
                ],
                "orphan_values": [
                    OrphanFieldValue(
                        field_id=dropped.pk,
                        name="Legacy question?",
                        display_value="Old answer",
                    )
                ],
            },
        )

    def test_get_shows_option_label_for_orphan_select_value(self, panel_client, event):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Which genre?",
            slug="genre",
            field_type="select",
            order=0,
        )
        SessionFieldOption.objects.create(
            field=field, label="Horror", value="horror", order=0
        )
        SessionFieldValue.objects.create(session=session, field=field, value="horror")

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "orphan_values": [
                    OrphanFieldValue(
                        field_id=field.pk, name="Which genre?", display_value="Horror"
                    )
                ],
            },
        )

    def test_get_shows_yes_for_orphan_checkbox_value(self, panel_client, event):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="Streaming",
            question="Allow streaming?",
            slug="streaming",
            field_type="checkbox",
            order=0,
        )
        SessionFieldValue.objects.create(session=session, field=field, value=True)

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "orphan_values": [
                    OrphanFieldValue(
                        field_id=field.pk, name="Allow streaming?", display_value="Yes"
                    )
                ],
            },
        )

    def test_get_shows_option_labels_for_orphan_multiselect_value(
        self, panel_client, event
    ):
        session = make_session(event)
        field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Which genres?",
            slug="genre",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        SessionFieldOption.objects.create(
            field=field, label="Horror", value="horror", order=0
        )
        SessionFieldOption.objects.create(
            field=field, label="Fantasy", value="fantasy", order=1
        )
        SessionFieldValue.objects.create(
            session=session, field=field, value=["horror", "fantasy"]
        )

        response = panel_client.get(form_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "orphan_values": [
                    OrphanFieldValue(
                        field_id=field.pk,
                        name="Which genres?",
                        display_value="Horror, Fantasy",
                    )
                ],
            },
        )

    def test_post_leaves_orphan_value_untouched_by_default(self, panel_client, event):
        session, _kept, dropped = self._orphan_setup(event)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "Pathfinder",
            },
        )

        value = SessionFieldValue.objects.get(session=session, field=dropped)
        assert value.value == "Old answer"

    def test_post_removes_orphan_value_when_checked(self, panel_client, event):
        session, _kept, dropped = self._orphan_setup(event)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "Pathfinder",
                "remove_field_ids": [dropped.pk],
            },
        )

        assert not SessionFieldValue.objects.filter(
            session=session, field=dropped
        ).exists()

    def test_post_ignores_removal_of_a_field_the_category_asks_for(
        self, panel_client, event
    ):
        session, kept, _dropped = self._orphan_setup(event)
        SessionFieldValue.objects.create(session=session, field=kept, value="Keep me")

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "Pathfinder",
                "remove_field_ids": [kept.pk],
            },
        )

        value = SessionFieldValue.objects.get(session=session, field=kept)
        assert value.value == "Pathfinder"

    def test_removing_an_orphan_is_recorded_in_the_content_log(
        self, panel_client, event
    ):
        session, _kept, dropped = self._orphan_setup(event)

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
                "session_system": "",
                "remove_field_ids": [dropped.pk],
            },
        )

        log = ContentChangeLog.objects.get(session=session)
        assert {
            "field": "",
            "field_id": dropped.pk,
            "old": "Old answer",
            "new": None,
        } in log.changes
