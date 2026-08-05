"""Unit tests for build_session_details_form with participant limit parameters."""

from ludamus.gates.web.django.chronology.forms import build_session_details_form

SESSION_DATA = {
    "title": "Test",
    "description": "A test session",
    "display_name": "Presenter",
}


class TestBuildSessionDetailsFormParticipantLimits:
    def test_no_min_makes_field_optional(self):
        form_class = build_session_details_form([], min_limit=0)
        form = form_class()

        field = form.fields["participants_limit"]
        assert field.required is False
        assert field.min_value == 0
        assert field.initial == 0

    def test_no_min_accepts_zero(self):
        form_class = build_session_details_form([], min_limit=0)
        form = form_class(SESSION_DATA | {"participants_limit": "0"})

        assert form.is_valid()
        assert form.cleaned_data["participants_limit"] == 0

    def test_no_min_accepts_empty(self):
        form_class = build_session_details_form([], min_limit=0)
        form = form_class(SESSION_DATA | {"participants_limit": ""})

        assert form.is_valid()
        assert form.cleaned_data["participants_limit"] is None

    def test_min_set_enforces_min(self):
        form_class = build_session_details_form([], min_limit=5)
        form = form_class(SESSION_DATA | {"participants_limit": "3"})

        assert not form.is_valid()
        assert "participants_limit" in form.errors

    def test_min_set_accepts_valid(self):
        form_class = build_session_details_form([], min_limit=5)
        form = form_class(SESSION_DATA | {"participants_limit": "10"})

        assert form.is_valid()

    def test_no_upper_bound(self):
        form_class = build_session_details_form([], min_limit=5)
        form = form_class(SESSION_DATA | {"participants_limit": "500"})

        assert form.is_valid()
        assert form.fields["participants_limit"].max_value is None

    def test_default_limits_are_zero(self):
        form_class = build_session_details_form([])
        form = form_class()

        field = form.fields["participants_limit"]
        assert field.required is False
        assert field.min_value == 0


class TestBuildSessionDetailsFormDurations:
    def test_no_duration_field_when_durations_is_none(self):
        form_class = build_session_details_form([], durations=None)
        form = form_class()

        assert "duration" not in form.fields

    def test_no_duration_field_when_durations_is_empty(self):
        form_class = build_session_details_form([], durations=[])
        form = form_class()

        assert "duration" not in form.fields

    def test_duration_field_present_when_durations_provided(self):
        form_class = build_session_details_form([], durations=["PT30M", "PT1H"])
        form = form_class()

        assert "duration" in form.fields

    def test_duration_choices_include_empty_sentinel(self):
        form_class = build_session_details_form([], durations=["PT30M"])
        form = form_class()

        choices = form.fields["duration"].choices
        assert choices[0] == ("", "---")

    def test_duration_choices_include_one_entry_per_duration(self):
        durations = ["PT30M", "PT1H", "PT1H30M"]
        form_class = build_session_details_form([], durations=durations)
        form = form_class()

        choices = form.fields["duration"].choices
        # sentinel + one per duration
        assert len(choices) == len(durations) + 1

    def test_duration_choices_use_human_readable_labels(self):
        form_class = build_session_details_form([], durations=["PT30M", "PT1H"])
        form = form_class()

        choice_map = dict(form.fields["duration"].choices)
        assert choice_map["PT30M"] == "30min"
        assert choice_map["PT1H"] == "1h"

    def test_duration_field_is_required(self):
        form_class = build_session_details_form([], durations=["PT30M"])
        form = form_class()

        assert form.fields["duration"].required is True
