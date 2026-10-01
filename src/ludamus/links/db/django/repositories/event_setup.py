from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ludamus.links.db.django.models import (
    DiscountRule,
    Event,
    EventPanelSettings,
    EventProposalSettings,
    PersonalDataField,
    PersonalDataFieldRequirement,
    ProposalCategory,
    SessionField,
    SessionFieldRequirement,
    Space,
    TimeSlot,
    TimeSlotRequirement,
    Track,
)
from ludamus.pacts.event import EventSetupRepositoryProtocol

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from django.db import models

_FIELD_COLUMN_PREFIX = "field_"


def _clone[M: models.Model](instance: M, **overrides: object) -> M:
    instance.pk = None
    for name, value in overrides.items():
        setattr(instance, name, value)
    instance.save()
    return instance


@dataclass(frozen=True, kw_only=True)
class _Copied:
    slots: dict[int, int]
    session_fields: dict[int, int]
    personal_fields: dict[int, int]


def _shifted(moment: datetime | None, shift: timedelta) -> datetime | None:
    return None if moment is None else moment + shift


def _remap_columns(columns: list[str], field_map: dict[int, int]) -> list[str]:
    remapped = []
    for column in columns:
        if not column.startswith(_FIELD_COLUMN_PREFIX):
            remapped.append(column)
        elif (old_pk := int(column.removeprefix(_FIELD_COLUMN_PREFIX))) in field_map:
            remapped.append(f"{_FIELD_COLUMN_PREFIX}{field_map[old_pk]}")
    return remapped


class EventSetupRepository(EventSetupRepositoryProtocol):
    @staticmethod
    def copy(*, source_id: int, target_id: int, shift: timedelta) -> None:
        source = Event.objects.get(pk=source_id)
        Event.objects.filter(pk=target_id).update(
            address=source.address,
            auto_confirm_sessions=source.auto_confirm_sessions,
            description=source.description,
            allow_facilitator_session_edit=source.allow_facilitator_session_edit,
            use_session_cover_placeholders=source.use_session_cover_placeholders,
            use_participants_label=source.use_participants_label,
            proposal_start_time=_shifted(source.proposal_start_time, shift),
            proposal_end_time=_shifted(source.proposal_end_time, shift),
        )
        space_map = _copy_spaces(source_id=source_id, target_id=target_id)
        _copy_tracks(source_id=source_id, target_id=target_id, space_map=space_map)
        slot_map = {
            slot.pk: (
                _clone(
                    slot,
                    event_id=target_id,
                    start_time=slot.start_time + shift,
                    end_time=slot.end_time + shift,
                ).pk
            )
            for slot in TimeSlot.objects.filter(event_id=source_id)
        }
        session_field_map = _copy_fields(
            SessionField, source_id=source_id, target_id=target_id
        )
        personal_field_map = _copy_fields(
            PersonalDataField, source_id=source_id, target_id=target_id
        )
        _copy_categories(
            source_id=source_id,
            target_id=target_id,
            shift=shift,
            copied=_Copied(
                slots=slot_map,
                session_fields=session_field_map,
                personal_fields=personal_field_map,
            ),
        )
        _copy_settings(
            source_id=source_id,
            target_id=target_id,
            session_field_map=session_field_map,
            personal_field_map=personal_field_map,
        )
        for config in source.enrollment_configs.prefetch_related("domain_configs"):
            domains = list(config.domain_configs.all())
            new_config = _clone(
                config,
                event_id=target_id,
                start_time=config.start_time + shift,
                end_time=config.end_time + shift,
            )
            for domain in domains:
                _clone(domain, enrollment_config=new_config)
        for rule in DiscountRule.objects.filter(event_id=source_id):
            _clone(rule, event_id=target_id)


def _copy_spaces(*, source_id: int, target_id: int) -> dict[int, int]:
    children: dict[int | None, list[Space]] = defaultdict(list)
    for space in Space.objects.filter(event_id=source_id).order_by("pk"):
        children[space.parent_id].append(space)
    space_map: dict[int, int] = {}
    queue: deque[tuple[Space, int | None]] = deque(
        (root, None) for root in children[None]
    )
    while queue:
        space, new_parent_id = queue.popleft()
        old_pk = space.pk
        new_pk = _clone(space, event_id=target_id, parent_id=new_parent_id).pk
        space_map[old_pk] = new_pk
        queue.extend((child, new_pk) for child in children[old_pk])
    return space_map


def _copy_tracks(*, source_id: int, target_id: int, space_map: dict[int, int]) -> None:
    tracks = Track.objects.filter(event_id=source_id).prefetch_related(
        "spaces", "managers"
    )
    for track in tracks:
        space_ids = [space_map[space.pk] for space in track.spaces.all()]
        managers = list(track.managers.all())
        new_track = _clone(track, event_id=target_id)
        new_track.spaces.set(space_ids)
        new_track.managers.set(managers)


def _copy_fields(
    model: type[SessionField | PersonalDataField], *, source_id: int, target_id: int
) -> dict[int, int]:
    field_map: dict[int, int] = {}
    for field in model.objects.filter(event_id=source_id).prefetch_related("options"):
        old_pk = field.pk
        options = list(field.options.all())
        new_field = _clone(field, event_id=target_id)
        for option in options:
            _clone(option, field=new_field)
        field_map[old_pk] = new_field.pk
    return field_map


def _copy_categories(
    *, source_id: int, target_id: int, shift: timedelta, copied: _Copied
) -> None:
    categories = ProposalCategory.objects.filter(event_id=source_id)
    category_map = {
        category.pk: (
            _clone(
                category,
                event_id=target_id,
                start_time=_shifted(category.start_time, shift),
                end_time=_shifted(category.end_time, shift),
            ).pk
        )
        for category in categories
    }
    in_source = {"category__event_id": source_id}
    for session_requirement in SessionFieldRequirement.objects.filter(**in_source):
        _clone(
            session_requirement,
            category_id=category_map[session_requirement.category_id],
            field_id=copied.session_fields[session_requirement.field_id],
        )
    for personal_requirement in PersonalDataFieldRequirement.objects.filter(
        **in_source
    ):
        _clone(
            personal_requirement,
            category_id=category_map[personal_requirement.category_id],
            field_id=copied.personal_fields[personal_requirement.field_id],
        )
    for slot_requirement in TimeSlotRequirement.objects.filter(**in_source):
        _clone(
            slot_requirement,
            category_id=category_map[slot_requirement.category_id],
            time_slot_id=copied.slots[slot_requirement.time_slot_id],
        )


def _copy_settings(
    *,
    source_id: int,
    target_id: int,
    session_field_map: dict[int, int],
    personal_field_map: dict[int, int],
) -> None:
    if proposal := EventProposalSettings.objects.filter(event_id=source_id).first():
        _clone(proposal, event_id=target_id)
    if panel := EventPanelSettings.objects.filter(event_id=source_id).first():
        _clone(
            panel,
            event_id=target_id,
            facilitator_columns=_remap_columns(
                panel.facilitator_columns, personal_field_map
            ),
            proposal_columns=_remap_columns(panel.proposal_columns, session_field_map),
        )
