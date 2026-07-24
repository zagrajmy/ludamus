"""Unit tests for the merge reconcile helpers (unanimity and target defaults)."""

from ludamus.gates.web.django.chronology.panel.views.facilitators import (
    accreditation_reconcile,
    field_reconcile,
    name_reconcile,
)
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.pacts import FacilitatorDTO, PersonalDataFieldDTO
from ludamus.pacts.panel import FacilitatorMergeContextDTO
from ludamus.pacts.submissions import AccreditationType


def _facilitator(*, pk, display_name, accreditation="none"):
    return FacilitatorDTO(
        accreditation_type=accreditation,
        display_name=display_name,
        event_id=1,
        pk=pk,
        slug=f"facilitator-{pk}",
        user_id=None,
    )


def _field(*, pk=1, slug="diet"):
    return PersonalDataFieldDTO(
        field_type="text", name="Diet", order=0, pk=pk, question="Diet?", slug=slug
    )


def _merge_context(*, facilitators, fields, values):
    return FacilitatorMergeContextDTO(
        facilitators=facilitators, fields=fields, values=values
    )


class TestNameReconcile:
    def test_unanimous_name_yields_no_choices(self):
        facilitators = [
            _facilitator(pk=1, display_name="Adam Kowalski"),
            _facilitator(pk=2, display_name="Adam Kowalski"),
        ]

        choices, unanimous = name_reconcile(facilitators)

        assert not choices
        assert unanimous == "Adam Kowalski"

    def test_disagreement_preselects_target_name(self):
        facilitators = [
            _facilitator(pk=1, display_name="Adam Kowalski"),
            _facilitator(pk=2, display_name="Jan Wysocki"),
            _facilitator(pk=3, display_name="Adam Kowalski"),
        ]

        choices, unanimous = name_reconcile(facilitators)

        assert choices == [("Adam Kowalski", True), ("Jan Wysocki", False)]
        assert unanimous is None


class TestAccreditationReconcile:
    def test_unanimous_accreditation_yields_no_choices(self):
        facilitators = [
            _facilitator(pk=1, display_name="Adam Kowalski"),
            _facilitator(pk=2, display_name="Jan Wysocki"),
        ]

        choices, unanimous = accreditation_reconcile(facilitators)

        assert not choices
        assert unanimous == "none"

    def test_disagreement_preselects_target_accreditation(self):
        facilitators = [
            _facilitator(pk=1, display_name="Adam Kowalski", accreditation="guest"),
            _facilitator(pk=2, display_name="Jan Wysocki"),
            _facilitator(pk=3, display_name="Ewa Nowak", accreditation="guest"),
        ]

        choices, unanimous = accreditation_reconcile(facilitators)

        guest_label = ACCREDITATION_TYPE_LABELS[AccreditationType.GUEST]
        none_label = ACCREDITATION_TYPE_LABELS[AccreditationType.NONE]
        assert choices == [
            ("guest", guest_label, "Adam Kowalski, Ewa Nowak", True),
            ("none", none_label, "Jan Wysocki", False),
        ]
        assert unanimous is None


class TestFieldReconcile:
    def test_field_without_values_is_omitted(self):
        merge_context = _merge_context(
            facilitators=[
                _facilitator(pk=1, display_name="Adam Kowalski"),
                _facilitator(pk=2, display_name="Jan Wysocki"),
            ],
            fields=[_field()],
            values={},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert not conflicts
        assert not unanimous

    def test_unanimous_value_moves_to_hidden_entries(self):
        field = _field()
        merge_context = _merge_context(
            facilitators=[
                _facilitator(pk=1, display_name="Adam Kowalski"),
                _facilitator(pk=2, display_name="Jan Wysocki"),
                _facilitator(pk=3, display_name="Ewa Nowak"),
            ],
            fields=[field],
            values={2: {"diet": "Vegan"}, 3: {"diet": "Vegan"}},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert not conflicts
        assert unanimous == [(field.pk, 2)]

    def test_disagreement_preselects_the_target_holder(self):
        field = _field()
        merge_context = _merge_context(
            facilitators=[
                _facilitator(pk=1, display_name="Adam Kowalski"),
                _facilitator(pk=2, display_name="Jan Wysocki"),
            ],
            fields=[field],
            values={1: {"diet": "Vegan"}, 2: {"diet": "Vegetarian"}},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert conflicts == [
            (
                field,
                [
                    (1, "Vegan", "Adam Kowalski", True),
                    (2, "Vegetarian", "Jan Wysocki", False),
                ],
            )
        ]
        assert not unanimous

    def test_disagreement_without_target_value_falls_back_to_first(self):
        field = _field()
        merge_context = _merge_context(
            facilitators=[
                _facilitator(pk=1, display_name="Adam Kowalski"),
                _facilitator(pk=2, display_name="Jan Wysocki"),
                _facilitator(pk=3, display_name="Ewa Nowak"),
            ],
            fields=[field],
            values={2: {"diet": "Vegan"}, 3: {"diet": "Vegetarian"}},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert conflicts == [
            (
                field,
                [
                    (2, "Vegan", "Jan Wysocki", True),
                    (3, "Vegetarian", "Ewa Nowak", False),
                ],
            )
        ]
        assert not unanimous
