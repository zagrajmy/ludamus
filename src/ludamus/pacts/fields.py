"""Contracts for organizer-defined fields — session and personal-data alike.

Both kinds are the same shape: a question, a type, options, and the rules for
filling one in. They live in separate tables because they hang off different
owners, but nothing downstream of the repository needs to tell them apart, so
one DTO serves both and `icon` simply stays empty for personal-data fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

FieldValue = str | list[str] | bool | None

# The empty option offered above a single-select's real ones.
BLANK_CHOICE = ("", "—")


class OrganizerFieldOptionDTO(BaseModel):
    """One choice offered by a select-type field."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    order: int
    pk: int
    value: str


def _option_order(option: OrganizerFieldOptionDTO) -> tuple[int, str]:
    return option.order, option.label


class OrganizerFieldDTO(BaseModel):
    """An organizer-defined field: session field or personal-data field."""

    model_config = ConfigDict(from_attributes=True)

    allow_custom: bool = False
    field_type: Literal["text", "select", "checkbox"]
    help_text: str = ""
    # Session fields carry an icon; personal-data fields leave it empty.
    icon: str = ""
    is_multiple: bool = False
    is_public: bool = False
    max_length: int = 50
    name: str
    options: list[OrganizerFieldOptionDTO] = []
    order: int
    pk: int
    question: str
    slug: str

    # What the field looks like once configured. The form builds its widgets
    # from these and the tag renders from the same answers, so a select can't
    # validate against one option list and offer another.

    @property
    def offers_custom_input(self) -> bool:
        # A checkbox has nothing to customise; every other type with
        # allow_custom gets the companion write-in.
        return self.allow_custom and self.field_type != "checkbox"

    @property
    def sorted_options(self) -> list[OrganizerFieldOptionDTO]:
        # The organizer's order; label breaks ties so the list stays stable.
        return sorted(self.options, key=_option_order)

    @property
    def choices(self) -> list[tuple[str, str]]:
        # Blank first — multi-selects drop it, having no empty state to pick.
        return [
            BLANK_CHOICE,
            *((option.value, option.label) for option in self.sorted_options),
        ]

    @property
    def length_limit(self) -> int | None:
        # Organizers spell "no limit" as 0; Django spells it None.
        return self.max_length or None

    def control_required(self, *, is_required: bool) -> bool:
        # A write-in can stand in for a choice, so the control alone can no
        # longer enforce the requirement — the form checks the pair instead.
        return is_required and not self.offers_custom_input


@dataclass(frozen=True, slots=True)
class FieldAnswer:
    """What someone filled in for one field, plus how it must be validated."""

    value: FieldValue = None
    custom_value: str = ""
    errors: list[str] = dataclass_field(default_factory=list)
    custom_errors: list[str] = dataclass_field(default_factory=list)
    is_required: bool = False


class FieldDescriptor(TypedDict):
    """One field ready to render: what to ask, where to post it, what's filled in."""

    field: OrganizerFieldDTO
    name_prefix: str
    answer: FieldAnswer
