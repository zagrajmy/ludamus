"""Answer shaping for dynamic fields: a multi-value field holds a list."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from ludamus.pacts import PersonalFieldRequirementDTO, SessionFieldRequirementDTO

type FieldAnswer = str | list[str] | bool


def split_custom(raw: str) -> list[str]:
    values: list[str] = []
    for part in (part.strip() for part in raw.split(",")):
        if part and part not in values:
            values.append(part)
    return values


def merge_custom(
    *, chosen: FieldAnswer | None, custom: str, is_multiple: bool
) -> FieldAnswer:
    if isinstance(chosen, bool):
        return chosen
    if not is_multiple:
        return chosen or custom
    values = (
        [value for value in chosen if isinstance(value, str)]
        if isinstance(chosen, list)
        else []
    )
    for part in split_custom(custom):
        if part not in values:
            values.append(part)
    return values


def split_stored(
    *, stored: FieldAnswer | None, known: Collection[str], is_multiple: bool
) -> tuple[str | list[str], str]:
    if not isinstance(stored, str | list):
        return ([] if is_multiple else ""), ""
    values = (
        [value for value in stored if isinstance(value, str)]
        if isinstance(stored, list)
        else [stored]
    )
    chosen = [value for value in values if value in known]
    custom = ", ".join(value for value in values if value not in known)
    if is_multiple:
        return chosen, custom
    return (chosen[0] if chosen else ""), custom


type WizardData = dict[str, FieldAnswer | int | None]


def unfold_custom_answers(
    *,
    stored: WizardData,
    requirements: Sequence[PersonalFieldRequirementDTO | SessionFieldRequirementDTO],
    prefix: str,
) -> WizardData:
    initial: WizardData = dict(stored)
    for req in requirements:
        key = f"{prefix}_{req.field.slug}"
        value = initial.get(key)
        if req.field.field_type != "select" or not isinstance(value, str | list):
            continue
        chosen, custom = split_stored(
            stored=value,
            known={option.value for option in req.field.options},
            is_multiple=req.field.is_multiple,
        )
        initial[key] = chosen
        if custom and req.field.allow_custom:
            initial[f"{key}_custom"] = custom
    return initial


def fold_custom_answers(
    *,
    cleaned: WizardData,
    requirements: Sequence[PersonalFieldRequirementDTO | SessionFieldRequirementDTO],
    prefix: str,
) -> WizardData:
    folded: WizardData = {
        key: value for key, value in cleaned.items() if not key.endswith("_custom")
    }
    for req in requirements:
        key = f"{prefix}_{req.field.slug}"
        value = folded.get(key)
        if not req.field.allow_custom or isinstance(value, int) or value is None:
            continue
        folded[key] = merge_custom(
            chosen=value,
            custom=str(cleaned.get(f"{key}_custom") or ""),
            is_multiple=req.field.is_multiple,
        )
    return folded
