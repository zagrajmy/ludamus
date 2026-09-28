import pytest

from ludamus.gates.web.django.templatetags.cfp_tags import field_value_list
from ludamus.pacts import SessionFieldValueDTO


def _field(value):
    return SessionFieldValueDTO(
        field_name="Game type", field_question="Game type", value=value
    )


class TestFieldValueList:
    @pytest.mark.parametrize(
        ("value", "expected"), ((True, "Yes"), ("Freeform", "Freeform"))
    )
    def test_non_list_becomes_a_single_entry(self, value, expected):
        # A select field can carry a bool or a plain string; iterating those in a
        # template yields a TypeError or one entry per character.
        assert field_value_list(_field(value)) == [expected]
