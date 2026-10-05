from ludamus.mills.chronology import diff_session_content
from ludamus.pacts import SessionDTO, SessionFieldValueDTO


def _session(**overrides):
    base = {
        "title": "Old title",
        "facilitator_name": "Old host",
        "description": "old desc",
        "contact_email": "old@example.com",
        "participants_limit": 5,
        "min_age": 0,
        "duration": "",
        "cover_image_url": "",
    }
    base.update(overrides)
    return SessionDTO.model_construct(**base)


def _value(field_id, value):
    return SessionFieldValueDTO.model_construct(
        field_id=field_id, value=value, field_name=""
    )


class TestCoreColumns:
    def test_changed_title_is_logged(self):
        changes = diff_session_content(_session(), {"title": "New title"}, [], [])

        assert changes == [
            {"field": "title", "field_id": None, "old": "Old title", "new": "New title"}
        ]

    def test_unchanged_value_is_not_logged(self):
        changes = diff_session_content(_session(), {"title": "Old title"}, [], [])

        assert changes == []

    def test_every_changed_column_is_logged_under_its_own_name(self):
        update = {
            "title": "New title",
            "facilitator_name": "New host",
            "description": "new desc",
            "contact_email": "new@example.com",
            "duration": "PT2H",
            "category_id": 4,
            "participants_limit": 8,
            "min_age": 16,
        }

        changes = diff_session_content(_session(category_id=3), update, [], [])

        assert changes == [
            {
                "field": "title",
                "field_id": None,
                "old": "Old title",
                "new": "New title",
            },
            {
                "field": "facilitator_name",
                "field_id": None,
                "old": "Old host",
                "new": "New host",
            },
            {
                "field": "description",
                "field_id": None,
                "old": "old desc",
                "new": "new desc",
            },
            {
                "field": "contact_email",
                "field_id": None,
                "old": "old@example.com",
                "new": "new@example.com",
            },
            {"field": "duration", "field_id": None, "old": "", "new": "PT2H"},
            {"field": "category", "field_id": None, "old": 3, "new": 4},
            {"field": "participants_limit", "field_id": None, "old": 5, "new": 8},
            {"field": "min_age", "field_id": None, "old": 0, "new": 16},
        ]


class TestCoverImage:
    def test_clearing_absent_cover_is_not_logged(self):
        changes = diff_session_content(_session(), {"cover_image": ""}, [], [])

        assert changes == []

    def test_uploading_cover_is_logged(self):
        changes = diff_session_content(_session(), {"cover_image": object()}, [], [])

        assert changes == [
            {"field": "cover_image", "field_id": None, "old": "", "new": "(updated)"}
        ]


class TestSessionFields:
    def test_changed_field_value_is_logged(self):
        old = [_value(1, "D&D")]
        new = [{"session_id": 9, "field_id": 1, "value": "Pathfinder"}]

        changes = diff_session_content(_session(), {}, old, new)

        assert changes == [
            {"field": "", "field_id": 1, "old": "D&D", "new": "Pathfinder"}
        ]

    def test_an_unchanged_answer_does_not_hide_later_changes(self):
        old = [_value(1, "D&D"), _value(2, "vegan")]
        new = [
            {"session_id": 9, "field_id": 1, "value": "D&D"},
            {"session_id": 9, "field_id": 2, "value": "none"},
        ]

        changes = diff_session_content(_session(), {}, old, new)

        assert changes == [{"field": "", "field_id": 2, "old": "vegan", "new": "none"}]

    def test_blank_unanswered_field_is_not_logged(self):
        new = [{"session_id": 9, "field_id": 1, "value": ""}]

        changes = diff_session_content(_session(), {}, [], new)

        assert changes == []

    def test_first_answer_is_logged(self):
        new = [{"session_id": 9, "field_id": 1, "value": "D&D"}]

        changes = diff_session_content(_session(), {}, [], new)

        assert changes == [{"field": "", "field_id": 1, "old": None, "new": "D&D"}]

    def test_changed_category_is_logged(self):
        changes = diff_session_content(
            _session(category_id=3), {"category_id": 4}, [], []
        )

        assert changes == [{"field": "category", "field_id": None, "old": 3, "new": 4}]

    def test_clearing_an_existing_cover_is_logged(self):
        changes = diff_session_content(
            _session(cover_image_url="http://img/old.png"), {"cover_image": ""}, [], []
        )

        assert changes == [
            {
                "field": "cover_image",
                "field_id": None,
                "old": "http://img/old.png",
                "new": "",
            }
        ]
