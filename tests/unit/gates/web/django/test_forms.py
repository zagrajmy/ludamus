"""Unit tests for gates/web/django/forms.py."""

from ludamus.gates.web.django.forms import ProposalCategoryForm


class TestProposalCategoryFormParticipantLimits:
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
