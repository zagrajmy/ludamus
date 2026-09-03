import pytest

from ludamus.gates.web.django.templatetags.cfp_tags import field_value_list


class TestFieldValueList:
    def test_list_becomes_its_own_entries(self):
        assert field_value_list(["RPG", "Board game"]) == ["RPG", "Board game"]

    @pytest.mark.parametrize(
        ("value", "expected"), ((True, "Yes"), (False, "No"), ("Freeform", "Freeform"))
    )
    def test_non_list_becomes_a_single_entry(self, value, expected):
        # A select field can carry a bool or a plain string; iterating those in a
        # template yields a TypeError or one entry per character.
        assert field_value_list(value) == [expected]

    def test_empty_list_has_no_entries(self):
        assert field_value_list([]) == []
