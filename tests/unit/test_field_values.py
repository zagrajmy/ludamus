from ludamus.mills.field_values import split_imported_answers


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
