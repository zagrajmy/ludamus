import re
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY

from django.contrib.messages import get_messages

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.http import HttpResponse


class PageMatcher:
    def __init__(self, *, number: int, num_pages: int) -> None:
        self.number = number
        self.num_pages = num_pages

    def __eq__(self, other: object) -> bool:
        paginator = getattr(other, "paginator", None)
        return (
            getattr(other, "number", None) == self.number
            and getattr(paginator, "num_pages", None) == self.num_pages
        )

    def __hash__(self) -> int:
        return hash((self.number, self.num_pages))

    def __repr__(self) -> str:
        return f"PageMatcher(number={self.number}, num_pages={self.num_pages})"


class FormErrorsMatcher:
    def __init__(self, **errors: list[str]) -> None:
        self.errors = errors

    def __eq__(self, other: object) -> bool:
        return {
            field: list(messages)
            for field, messages in getattr(other, "errors", {}).items()
        } == self.errors

    def __hash__(self) -> int:
        return hash(tuple(self.errors))

    def __repr__(self) -> str:
        return f"FormErrorsMatcher({self.errors})"


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
            "guidance": ANY,
        },
        template_name="404_dynamic.html",
        messages=messages,
        **response_fields,
    )


def input_tag(content: str, pk: int) -> str:
    # The single <input> tag for a person's Include checkbox on the enroll
    # page, so a test can check its checked / disabled attributes without
    # depending on attribute order.
    match = re.search(rf'<input[^>]*name="user_{pk}"[^>]*>', content)
    assert match, f"no checkbox for user_{pk}"
    return match.group(0)
