from ludamus.mills.field_values import merge_custom, split_answers, split_stored


class TestSplitAnswers:
    def test_strips_blanks_and_duplicates(self):
        assert split_answers(" krew , przemoc,, krew ") == ["krew", "przemoc"]

    def test_empty_input_is_no_values(self):
        assert not split_answers("  ")


class TestMergeCustom:
    def test_multiple_keeps_chosen_and_appends_write_ins(self):
        assert merge_custom(
            chosen=["horror"], custom="krew, przemoc", is_multiple=True
        ) == ["horror", "krew", "przemoc"]

    def test_multiple_does_not_repeat_a_chosen_option(self):
        assert merge_custom(chosen=["horror"], custom="horror", is_multiple=True) == [
            "horror"
        ]

    def test_single_keeps_the_chosen_option(self):
        assert (
            merge_custom(chosen="horror", custom="krew", is_multiple=False) == "horror"
        )

    def test_single_falls_back_to_the_write_in(self):
        assert merge_custom(chosen="", custom="krew, przemoc", is_multiple=False) == (
            "krew, przemoc"
        )

    def test_checkbox_value_is_untouched(self):
        assert merge_custom(chosen=True, custom="krew", is_multiple=False) is True


class TestSplitStored:
    def test_multiple_separates_options_from_write_ins(self):
        assert split_stored(
            stored=["horror", "krew", "przemoc"], known={"horror"}, is_multiple=True
        ) == (["horror"], "krew, przemoc")

    def test_single_write_in_leaves_no_option_selected(self):
        assert split_stored(stored="krew", known={"horror"}, is_multiple=False) == (
            "",
            "krew",
        )

    def test_round_trips_through_merge_custom(self):
        chosen, custom = split_stored(
            stored=["horror", "krew"], known={"horror"}, is_multiple=True
        )

        assert merge_custom(chosen=chosen, custom=custom, is_multiple=True) == [
            "horror",
            "krew",
        ]

    def test_checkbox_value_has_no_write_in_part(self):
        assert split_stored(stored=True, known=set(), is_multiple=False) == ("", "")
