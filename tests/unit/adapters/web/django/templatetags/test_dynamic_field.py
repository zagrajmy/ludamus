from ludamus.adapters.web.django.templatetags.tessera.dynamic_field import (
    FieldAnswer,
    dynamic_field,
)
from ludamus.pacts import PersonalDataFieldDTO, SessionFieldDTO, SessionFieldOptionDTO


def _session_field(**overrides: object) -> SessionFieldDTO:
    defaults: dict[str, object] = {
        "field_type": "select",
        "name": "Tags",
        "order": 0,
        "pk": 1,
        "question": "What tags apply?",
        "slug": "tags",
        "options": [
            SessionFieldOptionDTO(label="RPG", order=0, pk=1, value="rpg"),
            SessionFieldOptionDTO(label="Board", order=1, pk=2, value="board"),
        ],
    }
    return SessionFieldDTO(**(defaults | overrides))  # type: ignore[arg-type]


class TestSelectShapes:
    def test_multi_select_renders_checkboxes_not_radios(self) -> None:
        field = _session_field(is_multiple=True)

        html = dynamic_field(field, name_prefix="session_field")

        assert 'type="checkbox"' in html
        assert 'type="radio"' not in html

    def test_single_select_renders_a_select_with_a_blank_option(self) -> None:
        field = _session_field(is_multiple=False)

        html = dynamic_field(field, name_prefix="session_field")

        assert "<select" in html
        assert 'value=""' in html

    def test_multi_select_checks_the_values_already_answered(self) -> None:
        field = _session_field(is_multiple=True)

        html = dynamic_field(field, name_prefix="session_field", answer=["board"])

        assert html.count("checked") == 1
        assert 'value="board"' in html

    def test_single_select_marks_the_answered_option(self) -> None:
        field = _session_field(is_multiple=False)

        html = dynamic_field(field, name_prefix="session_field", answer="rpg")

        assert "selected" in html


class TestOtherShapes:
    def test_checkbox_field_renders_one_box(self) -> None:
        field = _session_field(field_type="checkbox", options=[])

        html = dynamic_field(field, name_prefix="session_field", answer=True)

        assert 'type="checkbox"' in html
        assert "checked" in html

    def test_text_field_carries_its_value_and_max_length(self) -> None:
        field = _session_field(field_type="text", max_length=120, options=[])

        html = dynamic_field(field, name_prefix="session_field", answer="anything")

        assert 'value="anything"' in html
        assert 'maxlength="120"' in html


class TestSharedBehaviour:
    def test_input_name_combines_the_prefix_and_slug(self) -> None:
        field = _session_field(field_type="text", options=[])

        html = dynamic_field(field, name_prefix="session_field")

        assert 'name="session_field_tags"' in html

    def test_multi_select_option_ids_are_scoped_to_the_field(self) -> None:
        field = _session_field(is_multiple=True)

        html = dynamic_field(field, name_prefix="session_field")

        assert 'id="id_session_field_tags_0"' in html
        assert 'id="_0"' not in html

    def test_errors_render_for_every_shape(self) -> None:
        field = _session_field(field_type="text", options=[])

        html = dynamic_field(
            field, name_prefix="session", answer=FieldAnswer(errors=["Too long."])
        )

        assert "Too long." in html

    def test_allow_custom_adds_a_companion_input_keeping_its_value(self) -> None:
        field = _session_field(allow_custom=True, is_multiple=False)

        html = dynamic_field(
            field,
            name_prefix="session",
            answer=FieldAnswer(custom_value="Something else"),
        )

        assert 'name="session_tags_custom"' in html
        assert 'value="Something else"' in html

    def test_checkbox_field_gets_no_companion_input(self) -> None:
        field = _session_field(field_type="checkbox", allow_custom=True, options=[])

        html = dynamic_field(field, name_prefix="session")

        assert "_custom" not in html

    def test_personal_data_field_renders_without_an_icon(self) -> None:
        field = PersonalDataFieldDTO(
            field_type="select",
            is_multiple=True,
            name="Country",
            options=[],
            order=0,
            pk=1,
            question="What country?",
            slug="country",
        )

        html = dynamic_field(field, name_prefix="personal")

        assert "What country?" in html

    def test_required_field_is_marked(self) -> None:
        field = _session_field(field_type="text", options=[])

        html = dynamic_field(
            field, name_prefix="session", answer=FieldAnswer(is_required=True)
        )

        assert "*" in html
        assert "required" in html
