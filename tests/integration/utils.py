from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY

from django.contrib.messages import get_messages

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.http import HttpResponse


def _assert_messages(response, expected_messages: list[tuple[int, str]]):
    msgs = list(get_messages(response.wsgi_request))
    assert len(msgs) == len(expected_messages), len(msgs)
    for i, (level, message) in enumerate(expected_messages):
        assert msgs[i].level == level, msgs[i].level
        assert msgs[i].message == message, msgs[i].message


def assert_response(
    response: HttpResponse,
    status_code: HTTPStatus,
    *,
    messages: Iterable[tuple[int, str]] = (),
    contains: str | Iterable[str] = (),
    not_contains: str | Iterable[str] = (),
    **response_fields: Any,
) -> None:
    assert response.status_code == status_code, response.status_code
    _assert_messages(response, messages)

    default_fields = {"context_data": None, "template_name": None, "url": None}
    for key, value in (default_fields | response_fields).items():
        assert getattr(response, key, None) == value

    needles = [contains] if isinstance(contains, str) else list(contains)
    absent = [not_contains] if isinstance(not_contains, str) else list(not_contains)
    assert "" not in needles, "empty substring is not a meaningful content check"
    assert "" not in absent, "empty substring is not a meaningful content check"
    if needles or absent:
        content = response.content.decode()
        for needle in needles:
            assert needle in content, needle
        for needle in absent:
            assert needle not in content, needle


def assert_response_404(
    response: HttpResponse,
    *,
    messages: Iterable[tuple[int, str]] = (),
    **response_fields: Any,
) -> None:
    assert_response(
        response,
        status_code=HTTPStatus.NOT_FOUND,
        context_data={
            "error_code": HTTPStatus.NOT_FOUND,
            "title": ANY,
            "message": ANY,
            "subtitle": ANY,
            "icon": ANY,
        },
        template_name="404_dynamic.html",
        messages=messages,
        **response_fields,
    )
