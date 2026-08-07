"""Unit tests for build_session_details_form with participant limit parameters."""

from ludamus.gates.web.django.chronology.forms import build_session_details_form
from tests.unit.factories import category


class TestBuildSessionDetailsFormParticipantLimits:
    def test_both_limits_zero_makes_field_optional(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=0)
        )
        form = form_class()

        field = form.fields["participants_limit"]
        assert field.required is False
        assert field.min_value == 0
        assert field.initial == 0

    def test_both_limits_zero_accepts_zero(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=0)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "0",
            }
        )

        assert form.is_valid()
        assert form.cleaned_data["participants_limit"] == 0

    def test_both_limits_zero_accepts_empty(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=0)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "",
            }
        )

        assert form.is_valid()
        assert form.cleaned_data["participants_limit"] is None

    def test_only_min_set_enforces_min(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=5, max_participants_limit=0)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "3",
            }
        )

        assert not form.is_valid()
        assert "participants_limit" in form.errors

    def test_only_min_set_accepts_valid(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=5, max_participants_limit=0)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "10",
            }
        )

        assert form.is_valid()

    def test_only_max_set_enforces_max(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=10)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "15",
            }
        )

        assert not form.is_valid()
        assert "participants_limit" in form.errors

    def test_only_max_set_accepts_zero(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=10)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "0",
            }
        )

        assert form.is_valid()

    def test_both_limits_set_enforces_range(self):
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=3, max_participants_limit=10)
        )

        too_low = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "2",
            }
        )
        assert not too_low.is_valid()

        too_high = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "11",
            }
        )
        assert not too_high.is_valid()

        just_right = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": "5",
            }
        )
        assert just_right.is_valid()

    def test_rejects_a_limit_wider_than_the_column(self):
        # The storage bound rides a validator, so the public input still
        # carries no max attribute even with no category ceiling set.
        form_class = build_session_details_form(
            [], category=category(min_participants_limit=0, max_participants_limit=0)
        )
        form = form_class(
            {
                "title": "Test",
                "description": "A test session",
                "display_name": "Presenter",
                "participants_limit": str(2**31),
            }
        )

        assert not form.is_valid()
        assert form.errors["participants_limit"] == ["Enter a smaller number."]
        assert form.fields["participants_limit"].max_value is None

    def test_default_limits_are_zero(self):
        form_class = build_session_details_form([], category=category())
        form = form_class()

        field = form.fields["participants_limit"]
        assert field.required is False
        assert field.min_value == 0


class TestBuildSessionDetailsFormDurations:
    def test_no_duration_field_when_durations_is_none(self):
        form_class = build_session_details_form([], category=category())
        form = form_class()

        assert "duration" not in form.fields

    def test_no_duration_field_when_durations_is_empty(self):
        form_class = build_session_details_form([], category=category(durations=[]))
        form = form_class()

        assert "duration" not in form.fields

    def test_duration_field_present_when_durations_provided(self):
        form_class = build_session_details_form(
            [], category=category(durations=["PT30M", "PT1H"])
        )
        form = form_class()

        assert "duration" in form.fields

    def test_duration_choices_include_empty_sentinel(self):
        form_class = build_session_details_form(
            [], category=category(durations=["PT30M"])
        )
        form = form_class()

        choices = form.fields["duration"].choices
        assert choices[0] == ("", "---")

    def test_duration_choices_include_one_entry_per_duration(self):
        durations = ["PT30M", "PT1H", "PT1H30M"]
        form_class = build_session_details_form(
            [], category=category(durations=durations)
        )
        form = form_class()

        choices = form.fields["duration"].choices
        # sentinel + one per duration
        assert len(choices) == len(durations) + 1

    def test_duration_choices_use_human_readable_labels(self):
        form_class = build_session_details_form(
            [], category=category(durations=["PT30M", "PT1H"])
        )
        form = form_class()

        choice_map = dict(form.fields["duration"].choices)
        assert choice_map["PT30M"] == "30min"
        assert choice_map["PT1H"] == "1h"

    def test_duration_field_is_required(self):
        form_class = build_session_details_form(
            [], category=category(durations=["PT30M"])
        )
        form = form_class()

        assert form.fields["duration"].required is True
