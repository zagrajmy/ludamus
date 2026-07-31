from ludamus.adapters.web.django.templatetags.tessera.dynamic_field import field_context
from ludamus.pacts import FieldAnswer
from tests.unit.dtos import organizer_field_dto


class TestOptions:
    def test_options_follow_the_organizers_order(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="session", answer=FieldAnswer()
        )

        assert context["options"] == [
            ("board", "Board", False, "id_session_tags_0"),
            ("rpg", "RPG", False, "id_session_tags_1"),
        ]

    def test_choices_start_with_a_blank_option(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="session", answer=FieldAnswer()
        )

        assert context["choices"] == [("", "—"), ("board", "Board"), ("rpg", "RPG")]

    def test_answered_options_are_marked_selected(self) -> None:
        context = field_context(
            organizer_field_dto(is_multiple=True),
            name_prefix="session",
            answer=FieldAnswer(value=["board"]),
        )

        assert context["options"] == [
            ("board", "Board", True, "id_session_tags_0"),
            ("rpg", "RPG", False, "id_session_tags_1"),
        ]


class TestAnswerShapes:
    def test_a_single_answer_becomes_the_text_value(self) -> None:
        context = field_context(
            organizer_field_dto(field_type="text", options=[]),
            name_prefix="session",
            answer=FieldAnswer(value="anything"),
        )

        assert (context["text_value"], context["is_checked"]) == ("anything", True)

    def test_an_unanswered_field_has_no_text_value(self) -> None:
        context = field_context(
            organizer_field_dto(field_type="text", options=[]),
            name_prefix="session",
            answer=FieldAnswer(),
        )

        assert (context["text_value"], context["is_checked"]) == ("", False)

    def test_an_unticked_checkbox_selects_nothing(self) -> None:
        context = field_context(
            organizer_field_dto(field_type="checkbox", options=[]),
            name_prefix="session",
            answer=FieldAnswer(value=False),
        )

        assert context["options"] == []
        assert (context["text_value"], context["is_checked"]) == ("", False)


class TestNamesAndIds:
    def test_names_and_ids_combine_the_prefix_and_slug(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="session_field", answer=FieldAnswer()
        )

        assert context["name"] == "session_field_tags"
        assert context["input_id"] == "id_session_field_tags"
        assert context["custom_name"] == "session_field_tags_custom"
        assert context["custom_id"] == "id_session_field_tags_custom"

    def test_help_and_error_ids_describe_the_input(self) -> None:
        context = field_context(
            organizer_field_dto(help_text="Pick one."),
            name_prefix="session",
            answer=FieldAnswer(errors=["Too long."]),
        )

        assert context["help_id"] == "id_session_tags_help"
        assert context["error_id"] == "id_session_tags_error"
        assert context["described_by"] == "id_session_tags_help id_session_tags_error"

    def test_nothing_is_described_when_there_is_nothing_to_say(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="session", answer=FieldAnswer()
        )

        assert (context["help_id"], context["error_id"], context["described_by"]) == (
            "",
            "",
            "",
        )


class TestLabelling:
    def test_the_question_is_the_label(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="session", answer=FieldAnswer()
        )

        assert context["label"] == "What tags apply?"

    def test_a_personal_data_field_carries_no_icon(self) -> None:
        context = field_context(
            organizer_field_dto(), name_prefix="personal", answer=FieldAnswer()
        )

        assert not context["icon_name"]

    def test_a_session_field_carries_its_icon(self) -> None:
        context = field_context(
            organizer_field_dto(icon="sparkles"),
            name_prefix="session",
            answer=FieldAnswer(),
        )

        assert context["icon_name"] == "sparkles"

    def test_required_and_errors_come_from_the_answer(self) -> None:
        context = field_context(
            organizer_field_dto(),
            name_prefix="session",
            answer=FieldAnswer(is_required=True, errors=["Too long."]),
        )

        assert context["is_required"] is True
        assert context["errors"] == ["Too long."]

    def test_the_custom_value_is_carried_through(self) -> None:
        context = field_context(
            organizer_field_dto(allow_custom=True),
            name_prefix="session",
            answer=FieldAnswer(custom_value="Something else"),
        )

        assert context["custom_value"] == "Something else"


class TestTheWriteIn:
    def test_its_errors_get_their_own_id_and_description(self) -> None:
        context = field_context(
            organizer_field_dto(allow_custom=True, help_text="Pick one."),
            name_prefix="session",
            answer=FieldAnswer(custom_errors=["Too long."]),
        )

        assert context["custom_errors"] == ["Too long."]
        assert context["custom_error_id"] == "id_session_tags_custom_error"
        assert (
            context["custom_described_by"]
            == "id_session_tags_help id_session_tags_custom_error"
        )

    def test_a_failing_control_does_not_mark_the_write_in(self) -> None:
        context = field_context(
            organizer_field_dto(allow_custom=True),
            name_prefix="session",
            answer=FieldAnswer(errors=["Pick an option or type your own."]),
        )

        assert context["custom_errors"] == []
        assert not context["custom_error_id"]

    def test_a_checkbox_is_offered_no_write_in(self) -> None:
        context = field_context(
            organizer_field_dto(field_type="checkbox", allow_custom=True, options=[]),
            name_prefix="session",
            answer=FieldAnswer(),
        )

        assert context["offers_custom"] is False
