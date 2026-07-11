from ludamus.mills.chronology import diff_session_content
from ludamus.pacts import SessionDTO, SessionFieldValueDTO


def _session(**overrides):
    base = {
        "title": "Old title",
        "display_name": "Old host",
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

    def test_key_absent_from_update_is_ignored(self):
        changes = diff_session_content(_session(), {}, [], [])

        assert changes == []

    def test_numeric_change_is_logged(self):
        changes = diff_session_content(_session(), {"participants_limit": 12}, [], [])

        assert changes == [
            {"field": "participants_limit", "field_id": None, "old": 5, "new": 12}
        ]


class TestCoverImage:
    def test_clearing_existing_cover_is_logged(self):
        changes = diff_session_content(
            _session(cover_image_url="/media/old.png"), {"cover_image": ""}, [], []
        )

        assert changes == [
            {
                "field": "cover_image",
                "field_id": None,
                "old": "/media/old.png",
                "new": "",
            }
        ]

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

    def test_unchanged_field_value_is_not_logged(self):
        old = [_value(1, "D&D")]
        new = [{"session_id": 9, "field_id": 1, "value": "D&D"}]

        changes = diff_session_content(_session(), {}, old, new)

        assert changes == []

    def test_blank_unanswered_field_is_not_logged(self):
        new = [{"session_id": 9, "field_id": 1, "value": ""}]

        changes = diff_session_content(_session(), {}, [], new)

        assert changes == []

    def test_first_answer_is_logged(self):
        new = [{"session_id": 9, "field_id": 1, "value": "D&D"}]

        changes = diff_session_content(_session(), {}, [], new)

        assert changes == [{"field": "", "field_id": 1, "old": None, "new": "D&D"}]
