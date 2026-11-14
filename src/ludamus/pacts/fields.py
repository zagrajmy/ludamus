"""Contracts for organizer-defined fields — session and personal-data alike.

Both kinds are the same shape: a question, a type, options, and the rules for
filling one in. They live in separate tables because they hang off different
owners, but nothing downstream of the repository needs to tell them apart, so
one DTO serves both and `icon` simply stays empty for personal-data fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Literal, NotRequired, Protocol, TypedDict, TypeIs

from pydantic import BaseModel, ConfigDict

FieldValue = str | list[str] | bool | None

# The empty option offered above a single-select's real ones.
BLANK_CHOICE = ("", "—")

type SessionFieldType = Literal["text", "select", "checkbox"]
type PersonalFieldType = Literal["text", "select", "checkbox", "discord"]
# Personal-data field types whose answers are the same plain string, so a field
# can move between them without touching what proposers already answered.
type TextFieldKind = Literal["text", "discord"]
TEXT_FIELD_KINDS: frozenset[str] = frozenset({"text", "discord"})
_SESSION_FIELD_TYPES: frozenset[str] = frozenset({"text", "select", "checkbox"})
_PERSONAL_FIELD_TYPES: frozenset[str] = _SESSION_FIELD_TYPES | TEXT_FIELD_KINDS
# A required checkbox would only accept a tick, so it is never required: not by
# the organiser's flag, and not by a category asking for it.
UNREQUIRABLE_FIELD_TYPES: frozenset[str] = frozenset({"checkbox"})


def is_session_field_type(value: str) -> TypeIs[SessionFieldType]:
    return value in _SESSION_FIELD_TYPES


def is_personal_field_type(value: str) -> TypeIs[PersonalFieldType]:
    return value in _PERSONAL_FIELD_TYPES


def is_text_field_kind(value: str) -> TypeIs[TextFieldKind]:
    return value in TEXT_FIELD_KINDS


class FieldTypeSwitchError(Exception):
    """Only text and Discord fields may switch type; other answers don't fit."""


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
    field_type: PersonalFieldType
    help_text: str = ""
    # Session fields carry an icon; personal-data fields leave it empty.
    icon: str = ""
    is_multiple: bool = False
    is_public: bool = False
    # Personal-data fields carry the organiser's flag; session fields are
    # required per kind and leave it False.
    is_required: bool = False
    max_length: int = 50
    name: str
    options: list[OrganizerFieldOptionDTO] = []
    order: int
    pk: int
    question: str
    # Session fields only; personal-data fields never reach a session card.
    show_on_cards: bool = True
    slug: str

    # What the field looks like once configured. The form builds its widgets
    # from these and the tag renders from the same answers, so a select can't
    # validate against one option list and offer another.

    @property
    def can_be_required(self) -> bool:
        return self.field_type not in UNREQUIRABLE_FIELD_TYPES

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
        return is_required and self.can_be_required and not self.offers_custom_input


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


class SessionFieldValueDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allow_custom: bool = False
    field_icon: str = ""
    field_id: int = 0
    field_name: str
    field_question: str
    field_slug: str = ""
    field_order: int = 0
    field_type: str = "text"
    is_public: bool = False
    show_on_cards: bool = True
    value: str | list[str] | bool


@dataclass
class FieldUsageSummary:
    """A field DTO bundled with its usage counts across categories."""

    field: OrganizerFieldDTO
    required_count: int
    optional_count: int

    @property
    def is_used(self) -> bool:
        """Whether any category asks for this field.

        The same question `CFPSessionFieldService.delete` answers with
        `has_requirements`, from counts the page already has — so the list can
        say Delete is unavailable without another query.

        Returns:
            True when at least one category requires or offers the field.
        """
        return bool(self.required_count or self.optional_count)


class SessionFieldValueData(TypedDict):
    session_id: int
    field_id: int
    value: str | list[str] | bool


class PersonalDataFieldValueData(TypedDict):
    facilitator_id: int
    event_id: int
    field_id: int
    value: str | list[str] | bool


class OrganizerFieldFormData(TypedDict):
    """What the field forms share, personal-data and session alike.

    The type itself is not here: a personal-data field may be a Discord
    username and a session field may not, so each kind declares its own.
    """

    name: str
    slug: NotRequired[str]
    question: str
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool
    max_length: int
    help_text: str
    is_public: bool


class PersonalDataFieldCreateData(OrganizerFieldFormData):
    field_type: PersonalFieldType
    is_required: bool
    order: int


class PersonalDataFieldUpdateData(OrganizerFieldFormData):
    # No `field_type`: switching one is its own operation, so an edit leaves
    # the stored type alone unless `set_field_type` changes it.
    is_required: bool
    order: int


class SessionFieldCreateData(OrganizerFieldFormData):
    field_type: SessionFieldType
    icon: str


class SessionFieldUpdateData(TypedDict):
    name: str
    question: str
    max_length: int
    help_text: str
    icon: str
    is_public: bool
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool


class PersonalDataFieldRepositoryProtocol(Protocol):
    def create(
        self, event_id: int, data: PersonalDataFieldCreateData
    ) -> OrganizerFieldDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int: ...
    @staticmethod
    def has_values(pk: int) -> bool: ...
    @staticmethod
    def count_values(event_id: int) -> dict[int, int]: ...
    def list_by_event(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO: ...
    def update(
        self, pk: int, data: PersonalDataFieldUpdateData
    ) -> OrganizerFieldDTO: ...
    def set_field_type(
        self, pk: int, field_type: TextFieldKind
    ) -> OrganizerFieldDTO: ...


class SessionFieldRepositoryProtocol(Protocol):
    def create(
        self, event_id: int, data: SessionFieldCreateData
    ) -> OrganizerFieldDTO: ...
    @staticmethod
    def delete(pk: int) -> None: ...
    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int: ...
    @staticmethod
    def has_requirements(pk: int) -> bool: ...
    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]: ...
    def list_by_event(self, event_id: int) -> list[OrganizerFieldDTO]: ...
    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO: ...
    @staticmethod
    def show_on_cards_only(event_id: int, field_ids: list[int]) -> None: ...
    def update(self, pk: int, data: SessionFieldUpdateData) -> OrganizerFieldDTO: ...


class PersonalDataFieldValueRepositoryProtocol(Protocol):
    @staticmethod
    def save(entries: list[PersonalDataFieldValueData]) -> None: ...
    @staticmethod
    def read_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> dict[str, str | list[str] | bool]: ...
    @staticmethod
    def list_values_for_facilitators(
        facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    @staticmethod
    def list_field_ids_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> list[int]: ...
    @staticmethod
    def delete_by_facilitators(facilitator_ids: list[int]) -> None: ...
    @staticmethod
    def delete_for_facilitator_fields(
        facilitator_id: int, field_ids: list[int]
    ) -> int: ...


DEFAULT_FIELD_MAX_LENGTH = 50
