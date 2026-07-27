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


class OrganizerFieldOptionDTO(BaseModel):
    """One choice offered by a select-type field."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    order: int
    pk: int
    value: str


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


@dataclass(frozen=True, slots=True)
class FieldAnswer:
    """What someone filled in for one field, plus how it must be validated."""

    value: FieldValue = None
    custom_value: str = ""
    errors: list[str] = dataclass_field(default_factory=list)
    is_required: bool = False


class FieldDescriptor(TypedDict):
    """One field ready to render: what to ask, where to post it, what's filled in."""

    field: OrganizerFieldDTO
    name_prefix: str
    answer: FieldAnswer
