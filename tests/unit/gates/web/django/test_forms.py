"""Unit tests for gates/web/django/forms.py."""

from ludamus.gates.web.django.forms import ProposalCategoryForm, create_space_copy_form

CLAIM_WINDOW_MINUTES = 15


class TestCreateSpaceCopyForm:
    """Tests for create_space_copy_form."""

    def test_creates_form_with_event_choices(self):
        """Form is created with target_event field having the provided choices."""
        events = [(1, "Event One"), (2, "Event Two")]

        form_class = create_space_copy_form(events)
        form = form_class()

        assert form.fields["target_event"].choices == events

    def test_creates_form_with_empty_choices(self):
        """Form can be created with empty choices list."""
        form_class = create_space_copy_form([])
        form = form_class()

        assert form.fields["target_event"].choices == []

    def test_form_validates_with_valid_choice(self):
        """Form validates when a valid event is selected."""
        events = [(1, "Event One"), (2, "Event Two")]

        form_class = create_space_copy_form(events)
        form = form_class({"target_event": "1"})

        assert form.is_valid()
        assert form.cleaned_data["target_event"] == "1"

    def test_form_invalid_without_selection(self):
        """Form is invalid when no event is selected."""
        events = [(1, "Event One"), (2, "Event Two")]

        form_class = create_space_copy_form(events)
        form = form_class({})

        assert not form.is_valid()
        assert "target_event" in form.errors


class TestProposalCategoryFormParticipantLimits:
    def test_valid_when_min_less_than_max(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "min_participants_limit": "3",
                "max_participants_limit": "10",
            }
        )

        assert form.is_valid()

    def test_valid_when_both_zero(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "min_participants_limit": "0",
                "max_participants_limit": "0",
            }
        )

        assert form.is_valid()

    def test_invalid_when_min_exceeds_max(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "min_participants_limit": "10",
                "max_participants_limit": "5",
            }
        )

        assert not form.is_valid()

    def test_valid_when_only_min_set(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "min_participants_limit": "5",
                "max_participants_limit": "0",
            }
        )

        assert form.is_valid()

    def test_valid_when_only_max_set(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "min_participants_limit": "0",
                "max_participants_limit": "10",
            }
        )

        assert form.is_valid()

    def test_valid_when_both_empty(self):
        form = ProposalCategoryForm({"name": "RPG"})

        assert form.is_valid()

    def test_accepts_offer_claim_settings(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "promotion_mode": "offer_claim",
                "offer_claim_window_minutes": str(CLAIM_WINDOW_MINUTES),
            }
        )

        assert form.is_valid()
        assert form.cleaned_data["promotion_mode"] == "offer_claim"
        assert form.cleaned_data["offer_claim_window_minutes"] == CLAIM_WINDOW_MINUTES

    def test_rejects_zero_minute_claim_window(self):
        form = ProposalCategoryForm(
            {
                "name": "RPG",
                "promotion_mode": "offer_claim",
                "offer_claim_window_minutes": "0",
            }
        )

        assert not form.is_valid()
        assert "offer_claim_window_minutes" in form.errors
