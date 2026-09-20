import pytest
from django.db import IntegrityError

from ludamus.links.db.django.models import PersonalDataField
from ludamus.links.db.django.repositories import PersonalDataFieldRepository
from tests.integration.conftest import EventFactory


def _data(**overrides):
    return {
        "name": "Consent",
        "question": "Do you agree?",
        "field_type": "checkbox",
        "options": None,
        "is_multiple": False,
        "allow_custom": False,
        "max_length": 0,
        "help_text": "",
        "is_public": False,
        **overrides,
    }


class TestPersonalDataFieldRequired:
    def test_create_keeps_a_required_text_field_required(self):
        event = EventFactory.create()

        dto = PersonalDataFieldRepository().create(
            event.pk, _data(field_type="text", is_required=True, order=2)
        )

        field = PersonalDataField.objects.get(pk=dto.pk)
        assert (dto.is_required, dto.order) == (True, 1 + 1)
        assert (field.is_required, field.order) == (True, 1 + 1)

    def test_create_never_stores_a_required_checkbox(self):
        event = EventFactory.create()

        dto = PersonalDataFieldRepository().create(
            event.pk, _data(is_required=True, order=1)
        )

        assert dto.is_required is False
        assert PersonalDataField.objects.get(pk=dto.pk).is_required is False

    def test_update_never_stores_a_required_checkbox(self):
        event = EventFactory.create()
        field = PersonalDataField.objects.create(
            event=event,
            name="Consent",
            question="?",
            slug="consent",
            field_type="checkbox",
        )

        PersonalDataFieldRepository().update(
            field.pk,
            {
                "name": "Consent",
                "question": "?",
                "max_length": 0,
                "help_text": "",
                "is_public": False,
                "is_required": True,
                "order": 0,
                "options": None,
                "is_multiple": False,
                "allow_custom": False,
            },
        )

        field.refresh_from_db()
        assert field.is_required is False

    def test_database_refuses_a_required_checkbox(self):
        event = EventFactory.create()

        with pytest.raises(IntegrityError):
            PersonalDataField.objects.create(
                event=event,
                name="Consent",
                question="?",
                slug="consent",
                field_type="checkbox",
                is_required=True,
            )
