from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ludamus.pacts.durations import duration_from_parts, stepper_parts
from ludamus.pacts.submissions import DurationSpec

if TYPE_CHECKING:
    from django.http import QueryDict

    from ludamus.pacts.chronology import SourceQuestion
    from ludamus.pacts.submissions import QuestionTarget, QuestionValue


class OptionDuration(TypedDict):
    option: str
    hours: str
    minutes: str


def option_durations(
    question: SourceQuestion, target: QuestionTarget | None
) -> list[OptionDuration]:
    configured = target.values if target else {}
    rows: list[OptionDuration] = []
    for option in question.options:
        spec = configured.get(option)
        hours, minutes = stepper_parts(
            spec.iso if isinstance(spec, DurationSpec) else ""
        )
        rows.append({"option": option, "hours": hours, "minutes": minutes})
    return rows


def duration_values_from_post(post: QueryDict, index: int) -> dict[str, QuestionValue]:
    values: dict[str, QuestionValue] = {}
    for option, hours, minutes in zip(
        post.getlist(f"droption_{index}"),
        post.getlist(f"drhours_{index}"),
        post.getlist(f"drminutes_{index}"),
        strict=False,
    ):
        if option and (iso := duration_from_parts(hours=hours, minutes=minutes)):
            values[option] = DurationSpec(iso=iso)
    return values
