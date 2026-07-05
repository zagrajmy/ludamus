from collections import defaultdict
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Event,
    Session,
    Space,
    TimeSlot,
    Track,
)
from ludamus.links.db.django.repositories import slugs
from ludamus.pacts import (
    NotFoundError,
    SpaceDTO,
    SpaceRepositoryProtocol,
    TimeSlotDTO,
    TimeSlotRepositoryProtocol,
    TrackCreateData,
    TrackDTO,
    TrackRepositoryProtocol,
    TrackUpdateData,
)
from ludamus.pacts.venues import SpaceNodeDTO, SpaceTreeRepositoryProtocol

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.adapters.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


class SpaceRepository(SpaceRepositoryProtocol):
    @staticmethod
    def read(pk: int) -> SpaceDTO:
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        return SpaceDTO.model_validate(space)

    @staticmethod
    def delete(pk: int) -> None:
        Space.objects.filter(pk=pk).delete()

    @staticmethod
    def lock(pk: int) -> None:
        try:
            Space.objects.select_for_update().get(pk=pk)
        except Space.DoesNotExist as exception:
            raise NotFoundError from exception

    @staticmethod
    def list_by_event(event_pk: int) -> list[SpaceDTO]:
        spaces = Space.objects.filter(event_id=event_pk).order_by("order", "name")
        return [SpaceDTO.model_validate(space) for space in spaces]


class SpaceTreeRepository(SpaceTreeRepositoryProtocol):
    @staticmethod
    def list_tree(event_pk: int) -> list[SpaceNodeDTO]:
        # One query for the whole event; assemble the tree in Python.
        spaces = list(Space.objects.filter(event_id=event_pk).order_by("order", "name"))
        children_by_parent: dict[int | None, list[Space]] = defaultdict(list)
        for space in spaces:
            children_by_parent[space.parent_id].append(space)

        def build(space: Space, depth: int) -> SpaceNodeDTO:
            kids = children_by_parent.get(space.pk, [])
            return SpaceNodeDTO(
                pk=space.pk,
                event_id=space.event_id,
                parent_id=space.parent_id,
                name=space.name,
                slug=space.slug,
                capacity=space.capacity,
                description=space.description,
                order=space.order,
                depth=depth,
                is_leaf=not kids,
                children=[build(kid, depth + 1) for kid in kids],
            )

        return [build(root, 1) for root in children_by_parent.get(None, [])]

    def read(self, pk: int) -> SpaceNodeDTO:
        try:
            space = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        return self._node(space)

    @transaction.atomic
    def create(
        self,
        *,
        event_id: int,
        parent_id: int | None,
        name: str,
        capacity: int | None,
        description: str,
    ) -> SpaceNodeDTO:
        slug = self.generate_unique_slug(event_id, parent_id, slugify(name))
        max_order = Space.objects.filter(
            event_id=event_id, parent_id=parent_id
        ).aggregate(top=Max("order"))["top"]
        space = Space(
            event_id=event_id,
            parent_id=parent_id,
            name=name,
            slug=slug,
            capacity=capacity,
            description=description,
            order=(max_order if max_order is not None else -1) + 1,
        )
        space.full_clean()
        space.save()
        return self._node(space)

    @transaction.atomic
    def update(
        self,
        *,
        pk: int,
        name: str,
        capacity: int | None,
        description: str,
        parent_id: int | None,
    ) -> SpaceNodeDTO:
        try:
            space = Space.objects.select_for_update().get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        parent_changed = space.parent_id != parent_id
        # Re-derive the slug whenever the name or parent changes, so it stays
        # unique among the (new) siblings. full_clean() below is the backstop
        # for cycles, depth, and the leaf-with-session rule.
        if space.name != name or parent_changed:
            space.name = name
            space.parent_id = parent_id
            space.slug = self.generate_unique_slug(
                space.event_id, parent_id, slugify(name), exclude_pk=pk
            )
        if parent_changed:
            # Append to the end of the new parent's sibling list.
            max_order = (
                Space.objects.filter(event_id=space.event_id, parent_id=parent_id)
                .exclude(pk=pk)
                .aggregate(top=Max("order"))["top"]
            )
            space.order = (max_order if max_order is not None else -1) + 1
        space.capacity = capacity
        space.description = description
        space.full_clean()
        space.save()
        return self._node(space)

    @staticmethod
    def delete(pk: int) -> None:
        # FK parent on_delete=CASCADE removes the whole subtree.
        Space.objects.filter(pk=pk).delete()

    @staticmethod
    def reorder(parent_id: int | None, child_pks: list[int], event_id: int) -> None:
        # Constrain by event so a root-level reorder (parent_id=None) can only
        # touch spaces belonging to the caller's event, never another event's.
        space_map = {
            space.pk: space
            for space in Space.objects.filter(
                event_id=event_id, parent_id=parent_id, pk__in=child_pks
            )
        }
        for order, pk in enumerate(child_pks):
            space = space_map.get(pk)
            if space is not None and space.order != order:
                space.order = order
                space.save(update_fields=["order", "modification_time"])

    @staticmethod
    def subtree_has_sessions(pk: int) -> bool:
        event_pk = Space.objects.values_list("event_id", flat=True).get(pk=pk)
        children_by_parent: dict[int, list[int]] = defaultdict(list)
        for child_pk, parent_pk in Space.objects.filter(event_id=event_pk).values_list(
            "pk", "parent_id"
        ):
            children_by_parent[parent_pk].append(child_pk)

        subtree: list[int] = []

        def collect(node_pk: int) -> None:
            subtree.append(node_pk)
            for child_pk in children_by_parent.get(node_pk, []):
                collect(child_pk)

        collect(pk)
        # Lock the subtree's Space rows (deterministic pk order) so a concurrent
        # session assignment to any leaf below serialises behind this
        # check-then-delete — assign_session locks the same Space row first,
        # so its AgendaItem can't slip in before the cascade. Safe because the
        # sole caller runs inside delete_space's atomic() block.
        list(Space.objects.select_for_update().filter(pk__in=subtree).order_by("pk"))
        return AgendaItem.objects.filter(space_id__in=subtree).exists()

    @staticmethod
    def space_pks_with_sessions(event_id: int) -> frozenset[int]:
        # Spaces that directly hold a scheduled session — these can't become a
        # parent (a leaf-with-session can't turn into a branch). One query.
        return frozenset(
            AgendaItem.objects.filter(space__event_id=event_id)
            .values_list("space_id", flat=True)
            .distinct()
        )

    @staticmethod
    def generate_unique_slug(
        event_id: int,
        parent_id: int | None,
        base_slug: str,
        exclude_pk: int | None = None,
    ) -> str:
        return slugs.generate_unique_slug(
            queryset=Space.objects.filter(event_id=event_id, parent_id=parent_id),
            base_slug=base_slug,
            exclude_pk=exclude_pk,
        )

    @transaction.atomic
    def duplicate(self, pk: int, new_name: str) -> SpaceNodeDTO:
        try:
            source = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        clone = self._clone_subtree(
            source, event_id=source.event_id, parent_id=source.parent_id, name=new_name
        )
        return self._node(clone)

    @transaction.atomic
    def copy_to_event(self, pk: int, target_event_id: int) -> SpaceNodeDTO:
        try:
            source = Space.objects.get(pk=pk)
        except Space.DoesNotExist as err:
            raise NotFoundError from err
        # The copied subtree becomes a root in the target event.
        clone = self._clone_subtree(source, event_id=target_event_id, parent_id=None)
        return self._node(clone)

    def _clone_subtree(
        self,
        source: Space,
        *,
        event_id: int,
        parent_id: int | None,
        name: str | None = None,
    ) -> Space:
        clone_name = name if name is not None else source.name
        clone = Space.objects.create(
            event_id=event_id,
            parent_id=parent_id,
            name=clone_name,
            slug=self.generate_unique_slug(event_id, parent_id, slugify(clone_name)),
            capacity=source.capacity,
            description=source.description,
            order=source.order,
        )
        for child in Space.objects.filter(parent_id=source.pk).order_by("order"):
            self._clone_subtree(child, event_id=event_id, parent_id=clone.pk)
        return clone

    @staticmethod
    def _node(space: Space) -> SpaceNodeDTO:
        return SpaceNodeDTO(
            pk=space.pk,
            event_id=space.event_id,
            parent_id=space.parent_id,
            name=space.name,
            slug=space.slug,
            capacity=space.capacity,
            description=space.description,
            order=space.order,
            depth=1 + sum(1 for _ in space.iter_ancestors()),
            is_leaf=not space.children.exists(),
            children=[],
        )


class TimeSlotRepository(TimeSlotRepositoryProtocol):
    @staticmethod
    def create(event_id: int, start_time: datetime, end_time: datetime) -> TimeSlotDTO:
        time_slot = TimeSlot.objects.create(
            event_id=event_id, start_time=start_time, end_time=end_time
        )
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def get_or_create(event_id: int, start_time: datetime, end_time: datetime) -> int:
        # Reuse a window the event already has (deduped by exact start+end) so
        # the importer can attach it without spawning duplicates on re-runs.
        time_slot, _ = TimeSlot.objects.get_or_create(
            event_id=event_id, start_time=start_time, end_time=end_time
        )
        return time_slot.pk

    @staticmethod
    def delete(pk: int) -> None:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist:
            return
        time_slot.delete()

    @staticmethod
    def has_proposals(pk: int) -> bool:
        return Session.objects.filter(time_slots=pk).exists()

    @staticmethod
    def list_by_event(event_id: int) -> list[TimeSlotDTO]:
        time_slots = TimeSlot.objects.filter(event_id=event_id).order_by("start_time")
        return [TimeSlotDTO.model_validate(ts) for ts in time_slots]

    @staticmethod
    def read(pk: int) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def read_by_event(event_id: int, pk: int) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk, event_id=event_id)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        return TimeSlotDTO.model_validate(time_slot)

    @staticmethod
    def update(pk: int, start_time: datetime, end_time: datetime) -> TimeSlotDTO:
        try:
            time_slot = TimeSlot.objects.get(pk=pk)
        except TimeSlot.DoesNotExist as exc:
            raise NotFoundError from exc
        time_slot.start_time = start_time
        time_slot.end_time = end_time
        time_slot.save()
        return TimeSlotDTO.model_validate(time_slot)


class TrackRepository(TrackRepositoryProtocol):
    @transaction.atomic
    def create(self, data: TrackCreateData) -> TrackDTO:
        Event.objects.select_for_update().get(pk=data["event_pk"])
        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(data["event_pk"], base_slug)
        track = Track.objects.create(
            event_id=data["event_pk"],
            name=data["name"],
            slug=slug,
            is_public=data["is_public"],
        )
        track.spaces.set(data["space_pks"])
        track.managers.set(data["manager_pks"])
        return TrackDTO.model_validate(track)

    @staticmethod
    def read(pk: int) -> TrackDTO:
        try:
            track = Track.objects.get(pk=pk)
        except Track.DoesNotExist as err:
            msg = f"Track with pk '{pk}' not found"
            raise NotFoundError(msg) from err
        return TrackDTO.model_validate(track)

    @staticmethod
    def read_by_slug(event_pk: int, slug: str) -> TrackDTO:
        try:
            track = Track.objects.get(event_id=event_pk, slug=slug)
        except Track.DoesNotExist as err:
            msg = f"Track with slug '{slug}' not found"
            raise NotFoundError(msg) from err
        return TrackDTO.model_validate(track)

    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int:
        track, _ = Track.objects.get_or_create(
            event_id=event_id, slug=slug, defaults={"name": name}
        )
        return track.pk

    @transaction.atomic
    def update(self, pk: int, data: TrackUpdateData) -> TrackDTO:
        try:
            track = Track.objects.select_for_update().get(pk=pk)
            Event.objects.select_for_update().get(pk=track.event_id)
        except Track.DoesNotExist as err:
            msg = f"Track with pk '{pk}' not found"
            raise NotFoundError(msg) from err
        needs_save = False
        if track.name != data["name"]:
            base_slug = slugify(data["name"])
            track.slug = self.generate_unique_slug(
                track.event_id, base_slug, exclude_pk=pk
            )
            track.name = data["name"]
            needs_save = True
        if track.is_public != data["is_public"]:
            track.is_public = data["is_public"]
            needs_save = True
        if needs_save:
            track.save()
        track.spaces.set(data["space_pks"])
        track.managers.set(data["manager_pks"])
        return TrackDTO.model_validate(track)

    @staticmethod
    def delete(pk: int) -> None:
        Track.objects.filter(pk=pk).delete()

    @staticmethod
    def list_by_event(event_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(event_id=event_pk).order_by("name")
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_public_by_event(event_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(event_id=event_pk, is_public=True).order_by(
            "name"
        )
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_by_manager(user_pk: int, event_pk: int | None = None) -> list[TrackDTO]:
        qs = Track.objects.filter(managers__pk=user_pk)
        if event_pk is not None:
            qs = qs.filter(event_id=event_pk)
        return [TrackDTO.model_validate(t) for t in qs.order_by("name")]

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        return slugs.generate_unique_slug(
            queryset=Track.objects.filter(event_id=event_id),
            base_slug=base_slug,
            exclude_pk=exclude_pk,
        )

    @staticmethod
    def list_space_pks(pk: int) -> list[int]:
        return list(Space.objects.filter(tracks__pk=pk).values_list("pk", flat=True))

    @staticmethod
    def list_manager_pks(pk: int) -> list[int]:
        return list(
            User.objects.filter(managed_tracks__pk=pk).values_list("pk", flat=True)
        )

    @staticmethod
    def list_by_session(session_pk: int) -> list[TrackDTO]:
        tracks = Track.objects.filter(sessions__pk=session_pk).order_by("name")
        return [TrackDTO.model_validate(t) for t in tracks]

    @staticmethod
    def list_manager_names(track_pk: int) -> list[str]:
        return list(
            User.objects.filter(managed_tracks__pk=track_pk)
            .order_by("name")
            .values_list("name", flat=True)
        )
