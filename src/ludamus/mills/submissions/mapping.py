"""Pure mapping helpers: import-row cells to domain values, titles to slugs."""

import re
from dataclasses import dataclass
from hashlib import blake2b
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Literal, Never

from pydantic import TypeAdapter, ValidationError
from unidecode import unidecode

from ludamus.pacts import PersonalDataFieldValueData, SessionFieldValueData
from ludamus.pacts.submissions import (
    DuplicateValueError,
    DurationSpec,
    EntityRef,
    FieldDefinition,
    ImportRow,
    ImportSettings,
    QuestionTarget,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def field_setup(
    definition: FieldDefinition | None,
) -> tuple[Literal["text", "select", "checkbox"], list[str] | None, bool, bool]:
    # Map a new-field definition to the (field_type, options, is_multiple,
    # allow_custom) a repo `create` expects; default to a plain text field.
    if definition is None:
        return "text", None, False, False
    return (
        definition.type,
        definition.options or None,
        definition.multiple,
        definition.allow_custom,
    )


_RESPONSE_ADAPTER = TypeAdapter(dict[str, str])

_BUILTIN_PROPOSAL_TARGETS = frozenset(
    {
        "session.title",
        "session.description",
        "session.duration",
        "session.participants_limit",
        "session.contact_email",
        "facilitator.display_name",
    }
)

_IDENTITY_TARGETS = frozenset({"session.title", "facilitator.display_name"})


@dataclass(frozen=True, slots=True)
class ResolvedBuiltins:
    title: str = ""
    description: str = ""
    duration: str = ""
    participants_limit: int = 0
    display_name: str = ""
    contact_email: str = ""


def resolve_builtins(settings: ImportSettings, row: ImportRow) -> ResolvedBuiltins:
    # First non-empty wins per built-in target: a later mapping with an empty
    # cell doesn't clobber an earlier resolved value (the parsers default to
    # 0 / "" on empty, which legacy duplicate mappings would otherwise spread
    # back across already-filled fields). Non-built-in targets are skipped so
    # `field.*` / `personal.*` conflicts surface during field-value population
    # with a more accurate per-row reason.
    title = ""
    description = ""
    duration = ""
    participants_limit = 0
    display_name = ""
    contact_email = ""
    for header, target in settings.questions.items():
        if target.to not in _BUILTIN_PROPOSAL_TARGETS:
            continue
        if not (value := cell(target=target, row=row, header=header)):
            continue
        if target.to == "session.title" and not title:
            title = value
        elif target.to == "session.description" and not description:
            description = value
        elif target.to == "session.duration" and not duration:
            duration = _duration_iso(target, header, value)
        elif target.to == "session.participants_limit" and not participants_limit:
            participants_limit = _parse_int(header, value)
        elif target.to == "session.contact_email" and not contact_email:
            contact_email = value
        elif target.to == "facilitator.display_name" and not display_name:
            display_name = value
    return ResolvedBuiltins(
        title=title,
        description=description,
        duration=duration,
        participants_limit=participants_limit,
        display_name=display_name,
        contact_email=contact_email,
    )


def extract_identity(settings: ImportSettings, row: ImportRow) -> tuple[str, str]:
    # Empty cells don't overwrite an earlier resolved value — a second
    # mapping to the same built-in target (e.g. legacy duplicates from
    # before the form-question dedup) would otherwise silently clobber it.
    # Only consult cells for the two targets this function consumes. This runs
    # outside the per-row try/except (it builds the log entry's display title),
    # so a conflicting or missing column must not raise here — fall back to a
    # blank display and let the per-row processing record the real reason.
    title = ""
    display_name = ""
    for header, target in settings.questions.items():
        if target.to not in _IDENTITY_TARGETS:
            continue
        try:
            value = cell(target=target, row=row, header=header)
        except RowSkippedError:
            continue
        if not value:
            continue
        if target.to == "session.title" and not title:
            title = value
        elif target.to == "facilitator.display_name" and not display_name:
            display_name = value
    # These feed the log entry's own CharField(max_length=255) columns, so a
    # failed over-length row can still be recorded — truncate for display.
    return title[:_MAX_LOG_CHAR_LENGTH], display_name[:_MAX_LOG_CHAR_LENGTH]


class RowSkippedError(Exception):
    # Raised inside the row-import machinery to signal that this single row
    # should be counted as skipped and the importer should move on, leaving
    # partial state for the row rolled back by the row-scoped savepoint.
    # `reason` is the operator-facing description that lands on the Log tab.
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DuplicateRowError(Exception):
    # Raised when settings.unique_key_columns matches a row already imported
    # into this event. Carries the existing session id so retry/run can link
    # the log entry back to it instead of leaving a stale skip reason.
    def __init__(self, existing_session_id: int) -> None:
        super().__init__()
        self.existing_session_id = existing_session_id


class MissingUniqueKeyColumnsError(Exception):
    # Raised when settings.unique_key_columns names headers the source sheet
    # doesn't carry (e.g. the English "Timestamp"/"Email Address" defaults saved
    # against a Polish-localized form whose real headers are "Sygnatura
    # czasowa"/"Adres e-mail"). Left silent, every row's identity collapses to
    # the columns that *do* match, so genuinely distinct rows share a slug and
    # get merged. Abort loudly instead of quietly losing proposals.
    def __init__(self, columns: list[str]) -> None:
        super().__init__(
            "Unique-key columns missing from the sheet: "
            + ", ".join(repr(c) for c in columns)
        )
        self.columns = columns


def field_name(definition: FieldDefinition | None, slug: str) -> str:
    # The display name comes from the definition; fall back to the slug when a
    # hand-written target carries no definition.
    return definition.name if definition and definition.name else slug


def _duration_iso(target: QuestionTarget, header: str, answer: str) -> str:
    # Per-option mapping: each source answer is looked up against the operator-
    # configured ISO durations on the target. A blank answer is treated as
    # "respondent left this question empty" — we trust the form data and leave
    # duration unset rather than skipping the row. An unmapped non-empty answer
    # still skips so an operator config error keeps surfacing.
    if not answer.strip():
        return ""
    spec = target.values.get(answer)
    if isinstance(spec, DurationSpec) and spec.iso:
        return spec.iso
    return _skip(f"{header}: unmapped duration answer '{answer}'")


def _parse_int(header: str, answer: str) -> int:
    # Pass-through numeric mapping (currently: participants_limit, a
    # PositiveIntegerField). Blank answers default to 0; non-numeric or
    # negative answers skip the row instead of crashing the insert.
    if not (text := (answer or "").strip()):
        return 0
    try:
        value = int(text)
    except ValueError:
        return _skip(f"{header}: '{answer}' is not an integer")
    if value < 0:
        return _skip(f"{header}: '{answer}' is negative")
    return value


def _skip(reason: str) -> Never:
    raise RowSkippedError(reason)


# The log entry's own title/display_name are CharField(max_length=255); a row
# that fails on an over-length value still has to be recorded, so truncate the
# display-only identity for storage.
_MAX_LOG_CHAR_LENGTH = 255


def cell(*, target: QuestionTarget | None, row: ImportRow, header: str) -> str:
    # Single read point for a row cell that a target consumes: applies the
    # operator-configured `overrides` substitution (raw cell text -> cleaned
    # cell text) before any parser, `values` lookup, or pass-through copy.
    # Lets a "maybe 8, maybe 10" answer become "10" for a numeric target, or a
    # typoed choice become the canonical option that the `values` map keys on.
    # `ImportRow.get_value` collapses sheet columns whose form questions were
    # already deduped (e.g. "Genre" + "Genre (2)") and raises on conflicting
    # non-empty values — surface that as a per-row skip.
    if target is not None and target.to and not row.has_column(header):
        return _skip(f"{header!r}: mapped column is missing from the response data")
    try:
        raw = row.get_value(header, "")
    except DuplicateValueError as exc:
        return _skip(
            f"{header}: duplicate values for column "
            f"({', '.join(repr(v) for v in exc.values)})"
        )
    if target is None or not target.overrides:
        return raw
    return target.overrides.get(raw, raw)


def session_field_values(
    *,
    field_ids: dict[str, int],
    settings: ImportSettings,
    row: ImportRow,
    session_id: int,
) -> list[SessionFieldValueData]:
    return [
        SessionFieldValueData(
            session_id=session_id,
            field_id=field_id,
            value=cell(target=settings.questions.get(header), row=row, header=header),
        )
        for header, field_id in field_ids.items()
    ]


def build_personal_data_field_values(
    *,
    field_ids: dict[str, int],
    settings: ImportSettings,
    row: ImportRow,
    facilitator_id: int,
    event_id: int,
) -> list[PersonalDataFieldValueData]:
    return [
        PersonalDataFieldValueData(
            facilitator_id=facilitator_id,
            event_id=event_id,
            field_id=field_id,
            value=cell(target=settings.questions.get(header), row=row, header=header),
        )
        for header, field_id in field_ids.items()
    ]


def chosen_entities(target: QuestionTarget, value: str) -> list[EntityRef]:
    # Each chosen option resolves to its configured entity; a custom or
    # unmatched answer falls through to the catchall when one is set. The
    # response cell joins multi-select answers with ", "; options are
    # comma-free, so a comma split + exact match resolves them.
    refs: list[EntityRef] = []
    for part in (part.strip() for part in value.split(",")):
        if not part:
            continue
        spec = target.values.get(part)
        if isinstance(spec, EntityRef):
            refs.append(spec)
        elif target.catchall is not None:
            refs.append(target.catchall)
    return refs


def decode_response(response_json: str) -> ImportRow:
    try:
        data = _RESPONSE_ADAPTER.validate_json(response_json or "{}")
    except ValidationError:
        data = {}
    return ImportRow(data)


def locate_row(
    *,
    rows: list[ImportRow],
    response: ImportRow,
    settings: ImportSettings,
    fallback_index: int,
) -> tuple[int, ImportRow] | None:
    # Settings.unique_key_columns names the columns whose values jointly
    # identify a row across re-fetches. Without it, fall back to the position
    # at the original attempt time — fine for sheets where the operator
    # doesn't shuffle rows between runs.
    if settings.unique_key_columns:
        target_key = {
            col: response.get_value(col, "") for col in settings.unique_key_columns
        }
        for idx, row in enumerate(rows):
            if all(
                row.get_value(col, "") == target_key[col]
                for col in settings.unique_key_columns
            ):
                return idx, row
        return None
    if fallback_index < len(rows):
        return fallback_index, rows[fallback_index]
    return None


def slugify(value: str, *, max_length: int = 50) -> str:
    # ASCII slug mirroring the live TS preview (simov/slugify with locale="pl").
    # Unidecode transliterates the full Unicode range (Polish ł/Ł, German ß,
    # CJK, etc.) rather than relying on NFKD decomposition, which silently
    # drops non-decomposable characters like ł. Capped at max_length to fit the
    # SlugField column (default 50); strip again so truncation never leaves a
    # trailing dash.
    transliterated = unidecode(value).lower()
    slug = re.sub(r"[^\w\s-]", "", transliterated)
    return re.sub(r"[-\s]+", "-", slug).strip("-")[:max_length].strip("-")


def dedup_slug(*, event_id: int, identity: str, max_length: int = 50) -> str:
    # Idempotency key for unique-key imports. Must fit the SlugField column, but
    # `slugify`'s bare truncation drops the tail — so two rows sharing a long
    # leading column (e.g. an identical session name) but differing in a later
    # column (email/facilitator) collapsed to one slug and got merged. Keep the
    # readable slug when the whole identity fits; otherwise reserve the tail for
    # a deterministic digest of the *full* identity so distinct rows never
    # collide. Short (already-correct) imports keep their existing slug.
    if not (full := slugify(f"e{event_id}-{identity}", max_length=len(identity) + 32)):
        return f"e{event_id}-row"
    if len(full) <= max_length:
        return full
    digest = blake2b(identity.encode(), digest_size=6).hexdigest()
    head = full[: max_length - len(digest) - 1].rstrip("-")
    return f"{head}-{digest}"


class SlugCollisionError(Exception):
    # Raised when a unique slug can't be found within the retry budget, so the
    # caller fails loudly instead of handing a colliding slug to the DB.
    def __init__(self, base_slug: str) -> None:
        super().__init__(f"Could not generate a unique slug for {base_slug!r}.")
        self.base_slug = base_slug


def generate_unique_slug(
    title: str,
    exists: Callable[[str], bool],
    *,
    fallback: str = "",
    max_attempts: int = 8,
    max_length: int = 50,
) -> str:
    base_slug = slugify(title, max_length=max_length) or fallback
    slug = base_slug
    for _ in range(max_attempts):
        if not exists(slug):
            return slug
        suffix = token_urlsafe(3)
        trimmed = base_slug[: max_length - len(suffix) - 1].rstrip("-")
        slug = f"{trimmed}-{suffix}"
    raise SlugCollisionError(base_slug)
