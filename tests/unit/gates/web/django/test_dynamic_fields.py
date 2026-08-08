from ludamus.gates.web.django.dynamic_fields import dynamic_fields_form
from tests.unit.factories import organizer_field_dto

CAPPED_LENGTH = 10


class TestTheFormMatchesWhatTheTagRenders:
    def test_a_single_select_validates_against_the_offered_choices(self):
        field = organizer_field_dto()

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert list(form.fields["session_tags"].choices) == field.choices

    def test_a_multi_select_drops_the_blank_the_tag_also_hides(self):
        field = organizer_field_dto(is_multiple=True)

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert list(form.fields["session_tags"].choices) == field.choices[1:]

    def test_a_write_in_is_capped_at_the_fields_length(self):
        field = organizer_field_dto(allow_custom=True, max_length=CAPPED_LENGTH)

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert form.fields["session_tags_custom"].max_length == CAPPED_LENGTH

    def test_zero_length_means_no_cap(self):
        field = organizer_field_dto(field_type="text", max_length=0, options=[])

        form = dynamic_fields_form(prefix="session", fields=[(field, False)])

        assert form.fields["session_tags"].max_length is None
