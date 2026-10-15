from typing import get_args

from ludamus.pacts.fields import (
    TEXT_FIELD_KINDS,
    PersonalFieldType,
    SessionFieldType,
    TextFieldKind,
    is_personal_field_type,
    is_session_field_type,
)


def test_text_kinds_match_their_literal():
    assert set(get_args(TextFieldKind.__value__)) == TEXT_FIELD_KINDS


def test_guards_accept_exactly_their_literal():
    personal = set(get_args(PersonalFieldType.__value__))
    session = set(get_args(SessionFieldType.__value__))

    assert {value for value in personal if is_personal_field_type(value)} == personal
    assert {value for value in personal if is_session_field_type(value)} == session
    assert not is_personal_field_type("date")
