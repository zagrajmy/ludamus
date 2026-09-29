from ludamus.gates.web.django.dynamic_fields import dynamic_fields_form
from tests.unit.factories import organizer_field_dto


class TestTheFormMatchesWhatTheTagRenders:
    def test_a_multi_select_drops_the_blank_the_tag_also_hides(self):
        field = organizer_field_dto(is_multiple=True)

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert list(form.fields["session_tags"].choices) == field.choices[1:]

    def test_zero_length_means_no_cap(self):
        field = organizer_field_dto(field_type="text", max_length=0, options=[])

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert form.fields["session_tags"].max_length is None
