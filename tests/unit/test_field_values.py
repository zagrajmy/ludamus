from ludamus.mills.field_values import (
    merge_custom,
    split_imported_answers,
    split_stored,
)


class TestSplitImportedAnswers:
    def test_strips_blanks_and_duplicates(self):
        assert split_imported_answers(" krew , przemoc,, krew ", ()) == [
            "krew",
            "przemoc",
        ]

    def test_a_known_option_keeps_its_comma(self):
        assert split_imported_answers(
            "przyciemnione światło, ściszone dźwięki, krew",
            {"przyciemnione światło, ściszone dźwięki"},
        ) == ["przyciemnione światło, ściszone dźwięki", "krew"]


class TestMergeCustom:
    def test_multiple_write_in_keeps_its_commas(self):
        assert merge_custom(
            chosen=[],
            custom="przyciemnione światło, ściszone dźwięki; brak migających świateł",
            is_multiple=True,
        ) == ["przyciemnione światło, ściszone dźwięki", "brak migających świateł"]

    def test_multiple_does_not_repeat_a_chosen_option(self):
        assert merge_custom(chosen=["horror"], custom="horror", is_multiple=True) == [
            "horror"
        ]

    def test_checkbox_value_is_untouched(self):
        assert merge_custom(chosen=True, custom="krew", is_multiple=False) is True


class TestSplitStored:
    def test_single_write_in_leaves_no_option_selected(self):
        assert split_stored(stored="krew", known={"horror"}, is_multiple=False) == (
            "",
            "krew",
        )

    def test_round_trips_a_write_in_containing_a_comma(self):
        stored = ["horror", "przyciemnione światło, ściszone dźwięki"]

        chosen, custom = split_stored(stored=stored, known={"horror"}, is_multiple=True)

        assert merge_custom(chosen=chosen, custom=custom, is_multiple=True) == stored
