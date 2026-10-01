from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from ludamus.mills import (
    generate_ics_content,
    google_calendar_url,
    outlook_calendar_url,
)
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    SlugCollisionError,
    cell,
    dedup_ident,
    extract_identity,
    field_answer,
    generate_unique_slug,
    resolve_builtins,
    session_field_values,
    slugify,
)
from ludamus.pacts import EncounterDTO, EventDTO, SessionFieldValueData
from ludamus.pacts.submissions import (
    FieldDefinition,
    FieldDefinitions,
    ImportRow,
    ImportSettings,
    QuestionTarget,
)


class TestIsProposalActive:
    @pytest.fixture
    def base_event_data(self):
        now = datetime.now(tz=UTC)
        return {
            "description": "Test event",
            "end_time": now + timedelta(days=7),
            "name": "Test Event",
            "pk": 1,
            "proposal_end_time": now + timedelta(days=1),
            "proposal_start_time": now - timedelta(days=1),
            "publication_time": now - timedelta(days=2),
            "slug": "test-event",
            "sphere_id": 1,
            "start_time": now + timedelta(days=5),
        }

    def test_returns_false_when_current_time_before_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now + timedelta(days=1)
        base_event_data["proposal_end_time"] = now + timedelta(days=2)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_event_not_yet_published(self, base_event_data):
        now = datetime.now(tz=UTC)
        base_event_data["publication_time"] = now + timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False


class TestLegacyCalendarWrappers:
    @staticmethod
    def _encounter(**overrides):
        start = datetime(2026, 8, 15, 12, 30, tzinfo=UTC)
        values = {
            "creation_time": start - timedelta(days=7),
            "creator_id": 1,
            "description": "A great session",
            "end_time": start + timedelta(hours=3),
            "game": "D&D",
            "max_participants": 6,
            "pk": 1,
            "place": "Room 42",
            "share_code": "ABC123",
            "sphere_id": 1,
            "start_time": start,
            "title": "My Encounter",
        }
        return EncounterDTO(**(values | overrides))

    @freeze_time("2026-08-01 09:00:00")
    def test_ics_content_uids_the_encounter_by_its_share_code(self):
        result = generate_ics_content(self._encounter(), "https://example.com/s/ABC123")

        assert result == (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Zagrajmy//Ludamus//PL\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:ABC123@ludamus\r\n"
            "DTSTAMP:20260801T090000Z\r\n"
            "DTSTART:20260815T123000Z\r\n"
            "DTEND:20260815T153000Z\r\n"
            "SUMMARY:My Encounter\r\n"
            "LOCATION:Room 42\r\n"
            "DESCRIPTION:A great session\r\n"
            "URL:https://example.com/s/ABC123\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_google_url_gives_an_open_ended_encounter_the_default_duration(self):
        encounter = self._encounter(end_time=None)

        result = google_calendar_url(encounter, "https://example.com/s/ABC123")

        assert result == (
            "https://calendar.google.com/calendar/render?action=TEMPLATE"
            "&text=My+Encounter"
            "&dates=20260815T123000Z%2F20260815T143000Z"
            "&details=A+great+session%0A%0Ahttps%3A%2F%2Fexample.com%2Fs%2FABC123"
            "&location=Room+42"
        )

    def test_outlook_url_gives_an_open_ended_encounter_the_default_duration(self):
        encounter = self._encounter(end_time=None)

        result = outlook_calendar_url(encounter, "https://example.com/s/ABC123")

        assert result == (
            "https://outlook.live.com/calendar/0/action/compose?rru=addevent"
            "&subject=My+Encounter"
            "&startdt=2026-08-15T12%3A30%3A00%2B00%3A00"
            "&enddt=2026-08-15T14%3A30%3A00%2B00%3A00"
            "&body=A+great+session%0A%0Ahttps%3A%2F%2Fexample.com%2Fs%2FABC123"
            "&location=Room+42"
        )


class TestMappingHelpers:
    MAX_CHAR_LENGTH = 255

    def test_answer_splits_a_multi_value_cell_into_a_list(self):
        settings = ImportSettings(
            questions={"Triggers": QuestionTarget(to="field.triggers")},
            definitions=FieldDefinitions(
                session_fields={
                    "triggers": FieldDefinition(
                        name="Triggers", type="select", multiple=True
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Triggers": "krew, przemoc"}),
            header="Triggers",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["krew", "przemoc"]

    def test_answer_keeps_an_option_that_contains_a_comma(self):
        settings = ImportSettings(
            questions={"Kind": QuestionTarget(to="field.kind")},
            definitions=FieldDefinitions(
                session_fields={
                    "kind": FieldDefinition(
                        name="Kind",
                        type="select",
                        multiple=True,
                        options=["Warsztaty, panele", "Prelekcja"],
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Kind": "Warsztaty, panele"}),
            header="Kind",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["Warsztaty, panele"]

    def test_answer_keeps_a_comma_bearing_option_beside_another(self):
        settings = ImportSettings(
            questions={"Kind": QuestionTarget(to="field.kind")},
            definitions=FieldDefinitions(
                session_fields={
                    "kind": FieldDefinition(
                        name="Kind",
                        type="select",
                        multiple=True,
                        options=["Warsztaty, panele", "Prelekcja"],
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Kind": "Warsztaty, panele, Prelekcja"}),
            header="Kind",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["Warsztaty, panele", "Prelekcja"]

    def test_answer_keeps_a_single_value_cell_as_text(self):
        settings = ImportSettings(
            questions={"System": QuestionTarget(to="field.system")},
            definitions=FieldDefinitions(
                session_fields={"system": FieldDefinition(name="System")}
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"System": "D&D, 5e"}),
            header="System",
            definitions=settings.definitions.session_fields,
        )

        assert value == "D&D, 5e"

    def test_answer_of_an_unmapped_header_is_the_stripped_text(self):
        value = field_answer(
            settings=ImportSettings(),
            row=ImportRow({"Note": " free text "}),
            header="Note",
            definitions={},
        )

        assert value == "free text"

    def test_answer_of_an_ignored_question_is_the_stripped_text(self):
        settings = ImportSettings(questions={"Note": QuestionTarget(ignore=True)})

        value = field_answer(
            settings=settings,
            row=ImportRow({"Note": "free text"}),
            header="Note",
            definitions={},
        )

        assert value == "free text"

    def test_answer_applies_the_target_overrides(self):
        settings = ImportSettings(
            questions={
                "Kind": QuestionTarget(to="field.kind", overrides={"ttrpg": "RPG"})
            }
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Kind": "ttrpg"}),
            header="Kind",
            definitions={},
        )

        assert value == "RPG"

    def test_answer_keys_the_definition_by_everything_after_the_prefix(self):
        settings = ImportSettings(
            questions={"Version": QuestionTarget(to="field.v1.0")},
            definitions=FieldDefinitions(
                session_fields={
                    "v1.0": FieldDefinition(
                        name="Version", type="select", multiple=True
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Version": "a, b"}),
            header="Version",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["a", "b"]

    def test_cell_skips_row_when_mapped_column_is_missing(self):
        target = QuestionTarget(to="track")
        row = ImportRow({"Title": "Talk"})

        with pytest.raises(RowSkippedError, match="missing"):
            cell(target=target, row=row, header="Block")

    def test_cell_names_the_conflicting_values_when_skipping(self):
        target = QuestionTarget(to="field.genre")
        row = ImportRow({"Genre": "Fantasy", "Genre (2)": "Sci-Fi"})

        with pytest.raises(RowSkippedError) as exc_info:
            cell(target=target, row=row, header="Genre")

        assert exc_info.value.reason == (
            "Genre: duplicate values for column ('Fantasy', 'Sci-Fi')"
        )

    def test_resolve_builtins_treats_whitespace_participants_limit_as_zero(self):
        settings = ImportSettings(
            questions={"Cap": QuestionTarget(to="session.participants_limit")}
        )

        builtins = resolve_builtins(settings, ImportRow({"Cap": "   "}))

        assert builtins.participants_limit == 0

    def test_resolve_builtins_skips_row_on_negative_participants_limit(self):
        settings = ImportSettings(
            questions={"Cap": QuestionTarget(to="session.participants_limit")}
        )

        with pytest.raises(RowSkippedError) as exc_info:
            resolve_builtins(settings, ImportRow({"Cap": "-5"}))

        assert exc_info.value.reason == "Cap: '-5' is negative"

    def test_extract_identity_truncates_over_long_values_for_logging(self):
        settings = ImportSettings(
            questions={
                "T": QuestionTarget(to="session.title"),
                "F": QuestionTarget(to="facilitator.display_name"),
            }
        )

        title, display_name = extract_identity(
            settings, ImportRow({"T": "x" * 300, "F": "y" * 300})
        )

        assert len(title) == self.MAX_CHAR_LENGTH
        assert len(display_name) == self.MAX_CHAR_LENGTH

    def test_session_field_values_stores_a_padded_answer_stripped(self):
        settings = ImportSettings(
            questions={"System": QuestionTarget(to="field.system")}
        )

        values = session_field_values(
            field_ids={"System": 55},
            settings=settings,
            row=ImportRow({"System": "  D&D  "}),
            session_id=7,
        )

        assert values == [SessionFieldValueData(session_id=7, field_id=55, value="D&D")]


class TestGenerateUniqueSlug:
    SUFFIX_LENGTH = 4  # token_urlsafe(3) as base64
    DEFAULT_ATTEMPTS = 8

    def test_appends_suffix_until_free(self):
        taken = {"my-talk"}

        slug = generate_unique_slug("My Talk", lambda s: s in taken)

        assert slug.startswith("my-talk-")
        assert len(slug) == len("my-talk-") + self.SUFFIX_LENGTH

    def test_raises_when_retry_budget_exhausted(self):
        with pytest.raises(SlugCollisionError) as exc_info:
            generate_unique_slug("My Talk", lambda _s: True, max_attempts=3)

        assert exc_info.value.base_slug == "my-talk"
        assert str(exc_info.value) == "Could not generate a unique slug for 'my-talk'."

    def test_tries_eight_slugs_by_default(self):
        tried: list[str] = []

        def taken(slug: str) -> bool:
            tried.append(slug)
            return True

        with pytest.raises(SlugCollisionError):
            generate_unique_slug("My Talk", taken)

        assert len(tried) == self.DEFAULT_ATTEMPTS

    def test_keeps_slug_within_max_length_with_suffix(self):
        taken = {slugify("x" * 80)}

        slug = generate_unique_slug("x" * 80, lambda s: s in taken)

        assert len(slug) == TestSlugify.MAX_SLUG_LENGTH
        assert slug not in taken

    def test_honours_a_custom_max_length(self):
        assert generate_unique_slug("x" * 80, lambda _s: False, max_length=10) == (
            "x" * 10
        )

    def test_strips_the_dash_the_cut_leaves_before_the_suffix(self):
        slug = generate_unique_slug(
            "aaaa bbbb", lambda s: s == "aaaa-bbbb", max_length=10
        )

        assert slug.startswith("aaaa-")
        assert len(slug) == len("aaaa-") + self.SUFFIX_LENGTH

    def test_without_a_fallback_an_unsluggable_title_yields_an_empty_slug(self):
        assert not generate_unique_slug("!!!", lambda _s: False)


class TestSlugify:
    MAX_SLUG_LENGTH = 50

    def test_truncation_drops_trailing_dash(self):
        # 49 chars then a space+word so the cut lands on a separator
        assert not slugify(f"{'a' * 49} bb").endswith("-")

    def test_caps_at_the_slug_column_width_by_default(self):
        assert len(slugify("x" * 80)) == self.MAX_SLUG_LENGTH

    def test_strips_a_leading_dash_before_capping(self):
        assert slugify(f"-{'a' * self.MAX_SLUG_LENGTH}") == "a" * self.MAX_SLUG_LENGTH


class TestDedupIdent:
    IDENT_LENGTH = 32  # blake2b digest_size=16 as hex

    def test_fits_the_ident_column(self):
        ident = dedup_ident(event_id=7, identity=f"{'name ' * 20}a@x.z")

        assert len(ident) == self.IDENT_LENGTH

    def test_same_name_different_tail_do_not_collide(self):
        # Regression: with slug-based dedup a long shared session name filled
        # the 50-char slug, truncating the distinguishing email away so two
        # distinct rows merged. The ident hashes the full identity.
        name = "A Very Long Session Title That Fills The Whole Slug Column"

        first = dedup_ident(event_id=7, identity=f"{name}-alice@example.com")
        second = dedup_ident(event_id=7, identity=f"{name}-bob@example.com")

        assert first != second

    def test_different_events_do_not_collide(self):
        assert dedup_ident(event_id=7, identity="a@x.z") != dedup_ident(
            event_id=8, identity="a@x.z"
        )
