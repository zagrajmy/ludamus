from __future__ import annotations

from collections import defaultdict, deque
from functools import partial
from typing import TYPE_CHECKING, Final

from django.utils.timezone import localtime, make_aware

from ludamus.links.db.django.models import (
    DiscountRule,
    DomainEnrollmentConfig,
    EnrollmentConfig,
    Event,
    EventPanelSettings,
    EventProposalSettings,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    ProposalCategory,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    Space,
    TimeSlot,
    TimeSlotRequirement,
    Track,
)
from ludamus.pacts.event import EventSetupRepositoryProtocol

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime, timedelta

    from django.db import models

    type _Value = int | datetime | list[str] | None

COPIED_RELATIONS: Final = frozenset(
    {
        DiscountRule,
        EnrollmentConfig,
        EventPanelSettings,
        EventProposalSettings,
        PersonalDataField,
        ProposalCategory,
        SessionField,
        Space,
        TimeSlot,
        Track,
    }
)
COPIED_FIELDS: Final = frozenset(
    {
        "address",
        "allow_facilitator_session_edit",
        "auto_confirm_sessions",
        "description",
        "proposal_end_time",
        "proposal_start_time",
        "use_participants_label",
        "use_session_cover_placeholders",
    }
)

_FIELD_COLUMN_PREFIX = "field_"


class _Mover:
    def __init__(self, *, source_start: datetime, target_start: datetime) -> None:
        self._shift: timedelta = _naive(target_start) - _naive(source_start)

    def __call__(self, moment: datetime) -> datetime:
        return make_aware(_naive(moment) + self._shift)

    def optional(self, moment: datetime | None) -> datetime | None:
        return None if moment is None else self(moment)


def _naive(moment: datetime) -> datetime:
    return localtime(moment).replace(tzinfo=None)


def _clone[M: models.Model](instance: M, **overrides: _Value) -> M:
    instance.pk = None
    for name, value in overrides.items():
        setattr(instance, name, value)
    instance.save()
    return instance


def _clone_each[M: models.Model](
    rows: Iterable[M], overrides: Callable[[M], dict[str, _Value] | None]
) -> dict[int, int]:
    copied: dict[int, int] = {}
    for row in rows:
        old_pk = row.pk
        if (values := overrides(row)) is not None:
            copied[old_pk] = _clone(row, **values).pk
    return copied


class EventSetupRepository(EventSetupRepositoryProtocol):
    @staticmethod
    def copy(*, source_id: int, target_id: int, start_time: datetime) -> None:
        source = Event.objects.get(pk=source_id)
        move = _Mover(source_start=source.start_time, target_start=start_time)
        Event.objects.filter(pk=target_id).update(
            **{name: getattr(source, name) for name in COPIED_FIELDS}
            | {
                "proposal_start_time": move.optional(source.proposal_start_time),
                "proposal_end_time": move.optional(source.proposal_end_time),
            }
        )
        spaces = _copy_spaces(source_id=source_id, target_id=target_id)
        _copy_tracks(source_id=source_id, target_id=target_id, spaces=spaces)
        slots = _clone_each(
            TimeSlot.objects.filter(event_id=source_id),
            lambda slot: {
                "event_id": target_id,
                "start_time": move(slot.start_time),
                "end_time": move(slot.end_time),
            },
        )
        session_fields = _copy_fields(
            SessionField, SessionFieldOption, source_id=source_id, target_id=target_id
        )
        personal_fields = _copy_fields(
            PersonalDataField,
            PersonalDataFieldOption,
            source_id=source_id,
            target_id=target_id,
        )
        categories = _clone_each(
            ProposalCategory.objects.filter(event_id=source_id),
            lambda category: {
                "event_id": target_id,
                "start_time": move.optional(category.start_time),
                "end_time": move.optional(category.end_time),
            },
        )
        for requirements, targets in (
            (
                SessionFieldRequirement.objects.filter(category__event_id=source_id),
                {"category_id": categories, "field_id": session_fields},
            ),
            (
                PersonalDataFieldRequirement.objects.filter(
                    category__event_id=source_id
                ),
                {"category_id": categories, "field_id": personal_fields},
            ),
            (
                TimeSlotRequirement.objects.filter(category__event_id=source_id),
                {"category_id": categories, "time_slot_id": slots},
            ),
        ):
            _clone_each(requirements, partial(_remapped, targets=targets))
        _copy_settings(
            source_id=source_id,
            target_id=target_id,
            session_fields=session_fields,
            personal_fields=personal_fields,
        )
        configs = _clone_each(
            EnrollmentConfig.objects.filter(event_id=source_id),
            lambda config: {
                "event_id": target_id,
                "start_time": move(config.start_time),
                "end_time": move(config.end_time),
            },
        )
        _clone_each(
            DomainEnrollmentConfig.objects.filter(
                enrollment_config__event_id=source_id
            ),
            lambda domain: _remapped(domain, {"enrollment_config_id": configs}),
        )
        _clone_each(
            DiscountRule.objects.filter(event_id=source_id),
            lambda _rule: {"event_id": target_id},
        )


def _remapped(
    row: models.Model, targets: dict[str, dict[int, int]]
) -> dict[str, _Value] | None:
    values: dict[str, _Value] = {}
    for name, mapped in targets.items():
        if (new_pk := mapped.get(getattr(row, name))) is None:
            return None
        values[name] = new_pk
    return values


def _copy_spaces(*, source_id: int, target_id: int) -> dict[int, int]:
    children: dict[int | None, list[Space]] = defaultdict(list)
    for space in Space.objects.filter(event_id=source_id).order_by("pk"):
        children[space.parent_id].append(space)
    copied: dict[int, int] = {}
    queue: deque[tuple[Space, int | None]] = deque(
        (root, None) for root in children[None]
    )
    while queue:
        space, new_parent_id = queue.popleft()
        old_pk = space.pk
        new_pk = _clone(space, event_id=target_id, parent_id=new_parent_id).pk
        copied[old_pk] = new_pk
        queue.extend((child, new_pk) for child in children[old_pk])
    return copied


def _copy_tracks(*, source_id: int, target_id: int, spaces: dict[int, int]) -> None:
    tracks = Track.objects.filter(event_id=source_id).prefetch_related(
        "spaces", "managers"
    )
    for track in tracks:
        space_ids = [spaces[s.pk] for s in track.spaces.all() if s.pk in spaces]
        managers = list(track.managers.all())
        new_track = _clone(track, event_id=target_id)
        new_track.spaces.set(space_ids)
        new_track.managers.set(managers)


def _copy_fields(
    model: type[SessionField | PersonalDataField],
    option_model: type[SessionFieldOption | PersonalDataFieldOption],
    *,
    source_id: int,
    target_id: int,
) -> dict[int, int]:
    fields = _clone_each(
        model.objects.filter(event_id=source_id), lambda _field: {"event_id": target_id}
    )
    _clone_each(
        option_model.objects.filter(field__event_id=source_id),
        lambda option: _remapped(option, {"field_id": fields}),
    )
    return fields


def _copy_settings(
    *,
    source_id: int,
    target_id: int,
    session_fields: dict[int, int],
    personal_fields: dict[int, int],
) -> None:
    if proposal := EventProposalSettings.objects.filter(event_id=source_id).first():
        _clone(proposal, event_id=target_id)
    if panel := EventPanelSettings.objects.filter(event_id=source_id).first():
        _clone(
            panel,
            event_id=target_id,
            facilitator_columns=_remap_columns(
                panel.facilitator_columns, personal_fields
            ),
            proposal_columns=_remap_columns(panel.proposal_columns, session_fields),
        )


def _remap_columns(columns: list[str], fields: dict[int, int]) -> list[str]:
    remapped = []
    for column in columns:
        if not column.startswith(_FIELD_COLUMN_PREFIX):
            remapped.append(column)
        elif (old_pk := int(column.removeprefix(_FIELD_COLUMN_PREFIX))) in fields:
            remapped.append(f"{_FIELD_COLUMN_PREFIX}{fields[old_pk]}")
    return remapped
