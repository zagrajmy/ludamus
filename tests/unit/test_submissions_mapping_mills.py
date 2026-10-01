from ludamus.mills.submissions.mapping import (
    MissingKeyColumnsError,
    chosen_entities,
    decode_response,
    extract_identity,
    field_setup,
    locate_row,
    resolve_builtins,
)
from ludamus.pacts.submissions import (
    DurationSpec,
    EntityRef,
    ImportRow,
    ImportSettings,
    QuestionTarget,
)

_RPG = EntityRef(name="RPG", slug="rpg")


class TestFieldSetup:
    def test_defaults_to_a_plain_text_field_without_a_definition(self):
        assert field_setup(None) == ("text", None, False, False)


class TestResolveBuiltins:
    def test_first_filled_mapping_of_a_built_in_wins(self):
        settings = ImportSettings(
            questions={
                "Name": QuestionTarget(to="facilitator.display_name"),
                "Nick": QuestionTarget(to="facilitator.display_name"),
                "Title": QuestionTarget(to="session.title"),
                "Subtitle": QuestionTarget(to="session.title"),
            }
        )
        row = ImportRow(
            {"Name": "Anna", "Nick": "Bartek", "Title": "One", "Subtitle": "Two"}
        )

        builtins = resolve_builtins(settings, row)

        assert (builtins.display_name, builtins.title) == ("Anna", "One")

    def test_an_override_that_blanks_the_answer_leaves_the_value_unset(self):
        settings = ImportSettings(
            questions={
                "Time": QuestionTarget(
                    to="session.duration",
                    values={"1h": DurationSpec(iso="PT1H")},
                    overrides={"dunno": " "},
                ),
                "Cap": QuestionTarget(
                    to="session.participants_limit", overrides={"n/a": " "}
                ),
            }
        )

        builtins = resolve_builtins(
            settings, ImportRow({"Time": "dunno", "Cap": "n/a"})
        )

        assert (builtins.duration, builtins.participants_limit) == ("", 0)


class TestExtractIdentity:
    _SETTINGS = ImportSettings(
        questions={
            "Title": QuestionTarget(to="session.title"),
            "Name": QuestionTarget(to="facilitator.display_name"),
            "Nick": QuestionTarget(to="facilitator.display_name"),
        }
    )

    def test_falls_back_to_blank_when_the_mapped_column_is_missing(self):
        assert extract_identity(self._SETTINGS, ImportRow({"Other": "x"})) == ("", "")

    def test_ignores_empty_cells(self):
        row = ImportRow({"Title": "", "Name": "", "Nick": ""})

        assert extract_identity(self._SETTINGS, row) == ("", "")

    def test_first_filled_display_name_mapping_wins(self):
        row = ImportRow({"Title": "Talk", "Name": "Anna", "Nick": "Bartek"})

        assert extract_identity(self._SETTINGS, row) == ("Talk", "Anna")


class TestMissingKeyColumnsError:
    def test_names_every_missing_column(self):
        error = MissingKeyColumnsError(["Timestamp", "Email Address"])

        assert error.columns == ["Timestamp", "Email Address"]
        assert str(error) == (
            "Key columns missing from the sheet: 'Timestamp', 'Email Address'"
        )


class TestChosenEntities:
    def test_skips_empty_parts_of_the_answer(self):
        target = QuestionTarget(to="track", values={"RPG": _RPG})

        assert chosen_entities(target, "RPG, , ,") == [_RPG]
        assert not chosen_entities(target, "")


class TestDecodeResponse:
    def test_malformed_json_decodes_to_an_empty_row(self):
        assert not decode_response("{not json").data
        assert not decode_response('{"a": [1]}').data


_ROWS = [
    ImportRow({"Email": "a@x", "Stamp": "1"}),
    ImportRow({"Email": "b@x", "Stamp": "1"}),
    ImportRow({"Email": "b@x", "Stamp": "2"}),
]


class TestLocateRow:
    _SETTINGS = ImportSettings(unique_key_columns=["Email", "Stamp"])

    def test_finds_the_row_matching_every_key_column(self):
        located = locate_row(
            rows=_ROWS,
            response=ImportRow({"Email": "b@x", "Stamp": "2"}),
            settings=self._SETTINGS,
            fallback_index=0,
        )

        assert located == (2, _ROWS[2])

    def test_returns_none_when_no_row_carries_the_key(self):
        located = locate_row(
            rows=_ROWS,
            response=ImportRow({"Email": "c@x", "Stamp": "1"}),
            settings=self._SETTINGS,
            fallback_index=0,
        )

        assert located is None
