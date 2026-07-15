import json
from typing import Literal, cast

from django.db.models import Count, Max, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.utils import timezone as django_timezone
from django.utils.text import slugify

from ludamus.adapters.db.django.models import (
    EventProposalSettings,
    Facilitator,
    ImportLogEntry,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    TimeSlotRequirement,
)
from ludamus.links.db.django.repositories import slugs
from ludamus.pacts import (
    CategoryStats,
    EventProposalSettingsDTO,
    EventProposalSettingsRepositoryProtocol,
    FacilitatorData,
    FacilitatorDTO,
    FacilitatorListItemDTO,
    FacilitatorRepositoryProtocol,
    FacilitatorUpdateData,
    NotFoundError,
    PersonalDataFieldCreateData,
    PersonalDataFieldDTO,
    PersonalDataFieldOptionDTO,
    PersonalDataFieldRepositoryProtocol,
    PersonalDataFieldUpdateData,
    PersonalDataFieldValueData,
    PersonalDataFieldValueRepositoryProtocol,
    PersonalFieldRequirementDTO,
    ProposalCategoryData,
    ProposalCategoryDTO,
    ProposalCategoryRepositoryProtocol,
    SessionFieldCreateData,
    SessionFieldDTO,
    SessionFieldOptionDTO,
    SessionFieldRepositoryProtocol,
    SessionFieldRequirementDTO,
    SessionFieldUpdateData,
    SessionStatus,
    TimeSlotDTO,
    TimeSlotRequirementDTO,
)
from ludamus.pacts.submissions import (
    FacilitatorListFilters,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogEntryRepositoryProtocol,
    ImportLogStatus,
)

# The DB stores field_type as a plain CharField; DTOs type it as this Literal.
_FieldType = Literal["text", "select", "checkbox"]

# Whitelist of sortable facilitator columns -> ORM field. `linked` sorts by
# user_id so linked/unlinked facilitators group together.
_FACILITATOR_SORT_FIELDS = {
    "name": "display_name",
    "accreditation": "accreditation_type",
    "sessions": "session_count",
    "linked": "user_id",
}


def _order_facilitators(qs: QuerySet[Facilitator], sort: str) -> QuerySet[Facilitator]:
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    # `field_<pk>` sorts by a personal-data column: annotate its value via a
    # correlated subquery. JSON values order by their text form — good enough
    # to line up near-duplicate entries.
    if key.startswith("field_") and key[len("field_") :].isdigit():
        field_id = int(key[len("field_") :])
        qs = qs.annotate(
            _sort_value=Subquery(
                PersonalDataFieldValue.objects.filter(
                    facilitator_id=OuterRef("pk"), field_id=field_id
                ).values("value")[:1]
            )
        )
        order_field = "_sort_value"
    else:
        order_field = _FACILITATOR_SORT_FIELDS.get(key, "display_name")
    order = f"-{order_field}" if descending else order_field
    return qs.order_by(order, "display_name", "pk")


class EventProposalSettingsRepository(EventProposalSettingsRepositoryProtocol):
    @staticmethod
    def read_or_create_by_event(event_id: int) -> EventProposalSettingsDTO:
        settings, _ = EventProposalSettings.objects.get_or_create(event_id=event_id)
        return EventProposalSettingsDTO.model_validate(settings)

    @staticmethod
    def read_by_event(event_id: int) -> EventProposalSettingsDTO:
        settings = EventProposalSettings.objects.filter(event_id=event_id).first()
        if settings is None:
            return EventProposalSettingsDTO(
                allow_anonymous_proposals=False, description="", pk=0
            )
        return EventProposalSettingsDTO.model_validate(settings)

    @staticmethod
    def update_allow_anonymous_proposals(event_id: int, *, allow: bool) -> None:
        settings, _ = EventProposalSettings.objects.get_or_create(event_id=event_id)
        settings.allow_anonymous_proposals = allow
        settings.save(update_fields=["allow_anonymous_proposals"])

    @staticmethod
    def update_description(event_id: int, description: str) -> None:
        settings, _ = EventProposalSettings.objects.get_or_create(event_id=event_id)
        settings.description = description
        settings.save(update_fields=["description"])


class ProposalCategoryRepository(ProposalCategoryRepositoryProtocol):  # noqa: PLR0904
    def create(self, event_id: int, name: str) -> ProposalCategoryDTO:
        base_slug = slugify(name)
        slug = self.generate_unique_slug(event_id, base_slug)

        category = ProposalCategory.objects.create(
            event_id=event_id, name=name, slug=slug
        )

        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def read_by_slug(event_id: int, slug: str) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(event_id=event_id, slug=slug)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def get_or_create_by_slug(event_id: int, name: str, slug: str) -> int:
        category, _ = ProposalCategory.objects.get_or_create(
            event_id=event_id, slug=slug, defaults={"name": name}
        )
        return category.pk

    _SIMPLE_UPDATE_FIELDS = (
        "description",
        "start_time",
        "end_time",
        "durations",
        "min_participants_limit",
        "max_participants_limit",
    )

    def update(self, pk: int, data: ProposalCategoryData) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(id=pk)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        needs_save = False

        if "name" in data and category.name != data["name"]:
            name = data["name"]
            category.name = name
            category.slug = self.generate_unique_slug(
                category.event_id, slugify(name), exclude_pk=pk
            )
            needs_save = True

        data_dict = cast("dict[str, object]", data)
        for field in self._SIMPLE_UPDATE_FIELDS:
            if field in data_dict and getattr(category, field) != data_dict[field]:
                setattr(category, field, data_dict[field])
                needs_save = True

        if needs_save:
            category.save()

        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def delete(pk: int) -> None:
        try:
            category = ProposalCategory.objects.get(id=pk)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception

        category.delete()

    @staticmethod
    def get_category_stats(event_id: int) -> dict[int, CategoryStats]:
        """Get proposal statistics for all categories of an event.

        Returns:
            Dict mapping category ID to CategoryStats with proposals_count
            and accepted_count.
        """
        categories = ProposalCategory.objects.filter(event_id=event_id).annotate(
            proposals_count=Count("sessions"),
            accepted_count=Count(
                "sessions", filter=~Q(sessions__status=SessionStatus.PENDING)
            ),
        )

        return {
            category.pk: CategoryStats(
                proposals_count=category.proposals_count,
                accepted_count=category.accepted_count,
            )
            for category in categories
        }

    @staticmethod
    def has_proposals(pk: int) -> bool:
        return Session.objects.filter(category_id=pk).exists()

    @staticmethod
    def list_by_event(event_id: int) -> list[ProposalCategoryDTO]:
        categories = ProposalCategory.objects.filter(event_id=event_id).order_by("name")
        return [ProposalCategoryDTO.model_validate(c) for c in categories]

    @staticmethod
    def get_field_requirements(category_id: int) -> dict[int, bool]:
        """Get field requirements for a category.

        Returns:
            Dict mapping field_id to is_required boolean.
        """
        requirements = PersonalDataFieldRequirement.objects.filter(
            category_id=category_id
        )
        return {req.field_id: req.is_required for req in requirements}

    @staticmethod
    def get_field_order(category_id: int) -> list[int]:
        """Get ordered list of field IDs for a category.

        Returns:
            List of field IDs ordered by their order field.
        """
        requirements = PersonalDataFieldRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.field_id for req in requirements]

    @staticmethod
    def set_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set field requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping field_id to is_required boolean.
            order: Optional list of field IDs defining the order.
        """
        PersonalDataFieldRequirement.objects.filter(category_id=category_id).delete()

        order_map = {fid: idx for idx, fid in enumerate(order or [])}

        for field_id, is_required in requirements.items():
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=order_map.get(field_id, 0),
            )

    @staticmethod
    def get_session_field_requirements(category_id: int) -> dict[int, bool]:
        """Get session field requirements for a category.

        Returns:
            Dict mapping field_id to is_required boolean.
        """
        requirements = SessionFieldRequirement.objects.filter(category_id=category_id)
        return {req.field_id: req.is_required for req in requirements}

    @staticmethod
    def get_session_field_order(category_id: int) -> list[int]:
        """Get ordered list of session field IDs for a category.

        Returns:
            List of field IDs ordered by their order field.
        """
        requirements = SessionFieldRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.field_id for req in requirements]

    @staticmethod
    def set_session_field_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set session field requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping field_id to is_required boolean.
            order: Optional list of field IDs defining the order.
        """
        SessionFieldRequirement.objects.filter(category_id=category_id).delete()

        order_map = {fid: idx for idx, fid in enumerate(order or [])}

        for field_id, is_required in requirements.items():
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=order_map.get(field_id, 0),
            )

    @staticmethod
    def add_field_to_categories(field_id: int, categories: dict[int, bool]) -> None:
        """Add a personal data field to multiple categories.

        Args:
            field_id: The field to add.
            categories: Dict mapping category_id to is_required boolean.
        """
        for category_id, is_required in categories.items():
            max_order = (
                PersonalDataFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def add_session_field_to_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        """Add a session field to multiple categories.

        Args:
            field_id: The field to add.
            categories: Dict mapping category_id to is_required boolean.
        """
        for category_id, is_required in categories.items():
            max_order = (
                SessionFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_personal_field_categories(field_id: int) -> dict[int, bool]:
        reqs = PersonalDataFieldRequirement.objects.filter(field_id=field_id)
        return {req.category_id: req.is_required for req in reqs}

    @staticmethod
    def set_personal_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        PersonalDataFieldRequirement.objects.filter(field_id=field_id).delete()
        for category_id, is_required in categories.items():
            max_order = (
                PersonalDataFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            PersonalDataFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_session_field_categories(field_id: int) -> dict[int, bool]:
        reqs = SessionFieldRequirement.objects.filter(field_id=field_id)
        return {req.category_id: req.is_required for req in reqs}

    @staticmethod
    def set_session_field_categories(
        field_id: int, categories: dict[int, bool]
    ) -> None:
        SessionFieldRequirement.objects.filter(field_id=field_id).delete()
        for category_id, is_required in categories.items():
            max_order = (
                SessionFieldRequirement.objects.filter(
                    category_id=category_id
                ).aggregate(Max("order"))["order__max"]
                or 0
            )
            SessionFieldRequirement.objects.create(
                category_id=category_id,
                field_id=field_id,
                is_required=is_required,
                order=max_order + 1,
            )

    @staticmethod
    def get_time_slot_requirements(category_id: int) -> dict[int, bool]:
        """Get time slot requirements for a category.

        Returns:
            Dict mapping time_slot_id to is_required boolean.
        """
        requirements = TimeSlotRequirement.objects.filter(category_id=category_id)
        return {req.time_slot_id: req.is_required for req in requirements}

    @staticmethod
    def get_time_slot_order(category_id: int) -> list[int]:
        """Get ordered list of time slot IDs for a category.

        Returns:
            List of time slot IDs ordered by their order field.
        """
        requirements = TimeSlotRequirement.objects.filter(
            category_id=category_id
        ).order_by("order")
        return [req.time_slot_id for req in requirements]

    @staticmethod
    def set_time_slot_requirements(
        category_id: int, requirements: dict[int, bool], order: list[int] | None = None
    ) -> None:
        """Set time slot requirements for a category.

        Replaces all existing requirements with the provided ones.

        Args:
            category_id: The category to set requirements for.
            requirements: Dict mapping time_slot_id to is_required boolean.
            order: Optional list of time slot IDs defining the order.
        """
        TimeSlotRequirement.objects.filter(category_id=category_id).delete()

        order_map = {ts_id: idx for idx, ts_id in enumerate(order or [])}

        for time_slot_id, is_required in requirements.items():
            TimeSlotRequirement.objects.create(
                category_id=category_id,
                time_slot_id=time_slot_id,
                is_required=is_required,
                order=order_map.get(time_slot_id, 0),
            )

    @staticmethod
    def read(pk: int, event_id: int) -> ProposalCategoryDTO:
        try:
            category = ProposalCategory.objects.get(pk=pk, event_id=event_id)
        except ProposalCategory.DoesNotExist as exception:
            raise NotFoundError from exception
        return ProposalCategoryDTO.model_validate(category)

    @staticmethod
    def list_personal_field_requirements(
        category_id: int,
    ) -> list[PersonalFieldRequirementDTO]:
        requirements = (
            PersonalDataFieldRequirement.objects.filter(category_id=category_id)
            .select_related("field")
            .prefetch_related(
                Prefetch(
                    "field__options",
                    queryset=PersonalDataFieldOption.objects.order_by("order", "label"),
                )
            )
            .order_by("order", "field__name")
        )
        result = []
        for req in requirements:
            field = req.field
            options = [
                PersonalDataFieldOptionDTO.model_validate(o)
                for o in field.options.all()
            ]
            field_dto = PersonalDataFieldDTO(
                allow_custom=field.allow_custom,
                field_type=cast("_FieldType", field.field_type),
                help_text=field.help_text,
                is_multiple=field.is_multiple,
                is_public=field.is_public,
                name=field.name,
                options=options,
                order=field.order,
                pk=field.pk,
                question=field.question,
                slug=field.slug,
            )
            result.append(
                PersonalFieldRequirementDTO(
                    field=field_dto, is_required=req.is_required
                )
            )
        return result

    @staticmethod
    def list_session_field_requirements(
        category_id: int,
    ) -> list[SessionFieldRequirementDTO]:
        requirements = (
            SessionFieldRequirement.objects.filter(category_id=category_id)
            .select_related("field")
            .prefetch_related(
                Prefetch(
                    "field__options",
                    queryset=SessionFieldOption.objects.order_by("order", "label"),
                )
            )
            .order_by("order", "field__name")
        )
        result = []
        for req in requirements:
            field = req.field
            options = [
                SessionFieldOptionDTO.model_validate(o) for o in field.options.all()
            ]
            field_dto = SessionFieldDTO(
                allow_custom=field.allow_custom,
                field_type=cast("_FieldType", field.field_type),
                help_text=field.help_text,
                icon=field.icon,
                is_multiple=field.is_multiple,
                is_public=field.is_public,
                name=field.name,
                options=options,
                order=field.order,
                pk=field.pk,
                question=field.question,
                slug=field.slug,
            )
            result.append(
                SessionFieldRequirementDTO(field=field_dto, is_required=req.is_required)
            )
        return result

    @staticmethod
    def list_time_slot_requirements(category_id: int) -> list[TimeSlotRequirementDTO]:
        requirements = (
            TimeSlotRequirement.objects.filter(category_id=category_id)
            .select_related("time_slot")
            .order_by("order", "time_slot__start_time")
        )
        return [
            TimeSlotRequirementDTO(
                time_slot=TimeSlotDTO.model_validate(req.time_slot),
                time_slot_id=req.time_slot_id,
                is_required=req.is_required,
            )
            for req in requirements
        ]

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        return slugs.generate_unique_slug(
            queryset=ProposalCategory.objects.filter(event_id=event_id),
            base_slug=base_slug,
            exclude_pk=exclude_pk,
        )


class PersonalDataFieldRepository(PersonalDataFieldRepositoryProtocol):
    def create(
        self, event_id: int, data: PersonalDataFieldCreateData
    ) -> PersonalDataFieldDTO:
        field_type = data["field_type"]
        options = data["options"]
        base_slug = data.get("slug") or slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

        actual_is_multiple = data["is_multiple"] if field_type == "select" else False
        actual_allow_custom = data["allow_custom"] if field_type == "select" else False

        field = PersonalDataField.objects.create(
            event_id=event_id,
            name=data["name"],
            question=data["question"],
            slug=slug,
            field_type=field_type,
            is_multiple=actual_is_multiple,
            allow_custom=actual_allow_custom,
            max_length=data["max_length"],
            help_text=data["help_text"],
            is_public=data["is_public"],
        )

        if field_type == "select" and options:
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    PersonalDataFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def delete(pk: int) -> None:
        PersonalDataField.objects.filter(pk=pk).delete()

    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int:
        # A PersonalDataField is orphan when no facilitator on this event has
        # a PersonalDataFieldValue entry that points at it. Used by the importer's
        # "Apply field layout" action after removing values for unmapped
        # fields.
        deleted, _ = (
            PersonalDataField.objects.filter(event_id=event_id)
            .annotate(usage=Count("values"))
            .filter(usage=0)
            .delete()
        )
        return deleted

    @staticmethod
    def has_requirements(pk: int) -> bool:
        """Check if a personal data field is used in any category requirements.

        Returns:
            True if the field is used in at least one category requirement.
        """
        return PersonalDataFieldRequirement.objects.filter(field_id=pk).exists()

    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]:
        rows = (
            PersonalDataFieldRequirement.objects.filter(field__event_id=event_id)
            .values("field_id")
            .annotate(
                required=Count("pk", filter=Q(is_required=True)),
                optional=Count("pk", filter=Q(is_required=False)),
            )
        )
        return {
            row["field_id"]: {"required": row["required"], "optional": row["optional"]}
            for row in rows
        }

    def list_by_event(self, event_id: int) -> list[PersonalDataFieldDTO]:
        fields = PersonalDataField.objects.filter(event_id=event_id).prefetch_related(
            "options"
        )
        return [self._to_dto(f) for f in fields]

    def read_by_slug(self, event_id: int, slug: str) -> PersonalDataFieldDTO:
        try:
            field = PersonalDataField.objects.prefetch_related("options").get(
                event_id=event_id, slug=slug
            )
        except PersonalDataField.DoesNotExist as exc:
            raise NotFoundError from exc

        return self._to_dto(field)

    def update(
        self, pk: int, data: PersonalDataFieldUpdateData
    ) -> PersonalDataFieldDTO:
        try:
            field = PersonalDataField.objects.prefetch_related("options").get(pk=pk)
        except PersonalDataField.DoesNotExist as exc:
            raise NotFoundError from exc

        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(field.event_id, base_slug, exclude_pk=pk)

        field.name = data["name"]
        field.question = data["question"]
        field.slug = slug
        field.max_length = data["max_length"]
        field.help_text = data["help_text"]
        field.is_public = data["is_public"]
        field.save()

        options = data["options"]
        if options is not None and field.field_type == "select":
            field.options.all().delete()
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    PersonalDataFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        return slugs.generate_unique_slug(
            queryset=PersonalDataField.objects.filter(event_id=event_id),
            base_slug=base_slug,
            exclude_pk=exclude_pk,
        )

    @staticmethod
    def _to_dto(field: PersonalDataField) -> PersonalDataFieldDTO:
        options = [
            PersonalDataFieldOptionDTO.model_validate(o) for o in field.options.all()
        ]
        return PersonalDataFieldDTO(
            allow_custom=field.allow_custom,
            field_type=cast("_FieldType", field.field_type),
            help_text=field.help_text,
            is_multiple=field.is_multiple,
            is_public=field.is_public,
            max_length=field.max_length,
            name=field.name,
            options=options,
            order=field.order,
            pk=field.pk,
            question=field.question,
            slug=field.slug,
        )


class SessionFieldRepository(SessionFieldRepositoryProtocol):
    def create(self, event_id: int, data: SessionFieldCreateData) -> SessionFieldDTO:
        field_type = data["field_type"]
        options = data["options"]
        base_slug = data.get("slug") or slugify(data["name"])
        slug = self.generate_unique_slug(event_id, base_slug)

        actual_is_multiple = data["is_multiple"] if field_type == "select" else False
        actual_allow_custom = data["allow_custom"] if field_type == "select" else False

        field = SessionField.objects.create(
            event_id=event_id,
            name=data["name"],
            question=data["question"],
            slug=slug,
            field_type=field_type,
            is_multiple=actual_is_multiple,
            allow_custom=actual_allow_custom,
            max_length=data["max_length"],
            help_text=data["help_text"],
            icon=data["icon"],
            is_public=data["is_public"],
        )

        if field_type == "select" and options:
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    SessionFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def delete(pk: int) -> None:
        SessionField.objects.filter(pk=pk).delete()

    @staticmethod
    def delete_orphans_for_event(event_id: int) -> int:
        # A SessionField is orphan when no session on this event has a
        # SessionFieldValue pointing at it. Used by the importer's "Apply
        # field layout" action.
        deleted, _ = (
            SessionField.objects.filter(event_id=event_id)
            .annotate(usage=Count("values"))
            .filter(usage=0)
            .delete()
        )
        return deleted

    @staticmethod
    def has_requirements(pk: int) -> bool:
        """Check if a session field is used in any category requirements.

        Returns:
            True if the field is used in at least one category requirement.
        """
        return SessionFieldRequirement.objects.filter(field_id=pk).exists()

    @staticmethod
    def get_usage_counts(event_id: int) -> dict[int, dict[str, int]]:
        rows = (
            SessionFieldRequirement.objects.filter(field__event_id=event_id)
            .values("field_id")
            .annotate(
                required=Count("pk", filter=Q(is_required=True)),
                optional=Count("pk", filter=Q(is_required=False)),
            )
        )
        return {
            row["field_id"]: {"required": row["required"], "optional": row["optional"]}
            for row in rows
        }

    def list_by_event(self, event_id: int) -> list[SessionFieldDTO]:
        fields = SessionField.objects.filter(event_id=event_id).prefetch_related(
            "options"
        )
        return [self._to_dto(f) for f in fields]

    def read_by_slug(self, event_id: int, slug: str) -> SessionFieldDTO:
        try:
            field = SessionField.objects.prefetch_related("options").get(
                event_id=event_id, slug=slug
            )
        except SessionField.DoesNotExist as exc:
            raise NotFoundError from exc

        return self._to_dto(field)

    def update(self, pk: int, data: SessionFieldUpdateData) -> SessionFieldDTO:
        try:
            field = SessionField.objects.prefetch_related("options").get(pk=pk)
        except SessionField.DoesNotExist as exc:
            raise NotFoundError from exc

        base_slug = slugify(data["name"])
        slug = self.generate_unique_slug(field.event_id, base_slug, exclude_pk=pk)

        field.name = data["name"]
        field.question = data["question"]
        field.slug = slug
        field.max_length = data["max_length"]
        field.help_text = data["help_text"]
        field.icon = data["icon"]
        field.is_public = data["is_public"]
        field.save()

        options = data["options"]
        if options is not None and field.field_type == "select":
            field.options.all().delete()
            for order, raw_option in enumerate(options):
                if option_label := raw_option.strip():
                    SessionFieldOption.objects.create(
                        field=field, label=option_label, value=option_label, order=order
                    )

        return self._to_dto(field)

    @staticmethod
    def generate_unique_slug(
        event_id: int, base_slug: str, exclude_pk: int | None = None
    ) -> str:
        return slugs.generate_unique_slug(
            queryset=SessionField.objects.filter(event_id=event_id),
            base_slug=base_slug,
            exclude_pk=exclude_pk,
        )

    @staticmethod
    def _to_dto(field: SessionField) -> SessionFieldDTO:
        options = [SessionFieldOptionDTO.model_validate(o) for o in field.options.all()]
        return SessionFieldDTO(
            allow_custom=field.allow_custom,
            field_type=cast("_FieldType", field.field_type),
            help_text=field.help_text,
            icon=field.icon,
            is_multiple=field.is_multiple,
            is_public=field.is_public,
            max_length=field.max_length,
            name=field.name,
            options=options,
            order=field.order,
            pk=field.pk,
            question=field.question,
            slug=field.slug,
        )


class FacilitatorRepository(FacilitatorRepositoryProtocol):
    @staticmethod
    def create(data: FacilitatorData) -> FacilitatorDTO:
        facilitator = Facilitator.objects.create(**data)
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read(pk: int) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(pk=pk)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_event_and_slug(event_id: int, slug: str) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(event_id=event_id, slug=slug)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def read_by_user_and_event(user_id: int, event_id: int) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(user_id=user_id, event_id=event_id)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def update(pk: int, data: FacilitatorUpdateData) -> FacilitatorDTO:
        try:
            facilitator = Facilitator.objects.get(pk=pk)
        except Facilitator.DoesNotExist as exc:
            raise NotFoundError from exc
        for field, value in data.items():
            setattr(facilitator, field, value)
        facilitator.save()
        return FacilitatorDTO.model_validate(facilitator)

    @staticmethod
    def list_by_event(
        event_id: int, filters: FacilitatorListFilters | None = None
    ) -> list[FacilitatorListItemDTO]:
        filters = filters or {}
        qs = Facilitator.objects.filter(event_id=event_id).annotate(
            session_count=Count("sessions", distinct=True)
        )

        if search := filters.get("search"):
            # Text personal-data values are stored JSON-encoded; match both the
            # raw string and its JSON-escaped form (mirrors proposals search).
            encoded = json.dumps(search)[1:-1]
            text_value = Q(personal_data__field__field_type="text") & (
                Q(personal_data__value__icontains=search)
                | Q(personal_data__value__icontains=encoded)
            )
            qs = qs.filter(
                Q(display_name__icontains=search)
                | Q(user__name__icontains=search)
                | text_value
            ).distinct()

        if accreditation := filters.get("accreditation"):
            qs = qs.filter(accreditation_type=accreditation)

        if filters.get("flagged"):
            qs = qs.filter(flagged_for_deletion=True)

        for field_id, value in (filters.get("field_filters") or {}).items():
            # Each condition is its own join, so different fields AND together.
            qs = qs.filter(personal_data__field_id=field_id, personal_data__value=value)

        ordered = _order_facilitators(qs, filters.get("sort") or "name")
        return [FacilitatorListItemDTO.model_validate(f) for f in ordered]

    @staticmethod
    def set_flag(pk: int, *, flagged: bool) -> None:
        Facilitator.objects.filter(pk=pk).update(flagged_for_deletion=flagged)

    @staticmethod
    def delete(pk: int) -> None:
        Facilitator.objects.filter(pk=pk).delete()

    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool:
        return Facilitator.objects.filter(event_id=event_id, slug=slug).exists()


class PersonalDataFieldValueRepository(PersonalDataFieldValueRepositoryProtocol):
    @staticmethod
    def save(entries: list[PersonalDataFieldValueData]) -> None:
        for entry in entries:
            PersonalDataFieldValue.objects.update_or_create(
                facilitator_id=entry["facilitator_id"],
                event_id=entry["event_id"],
                field_id=entry["field_id"],
                defaults={"value": entry["value"]},
            )

    @staticmethod
    def read_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> dict[str, str | list[str] | bool]:
        records = PersonalDataFieldValue.objects.filter(
            facilitator_id=facilitator_id, event_id=event_id
        ).select_related("field")
        return {hpd.field.slug: hpd.value for hpd in records}

    @staticmethod
    def list_values_for_facilitators(
        facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]:
        # Batch load for the facilitators list: one query for the current
        # page's facilitators across the chosen columns, keyed by facilitator_id.
        if not facilitator_ids or not field_ids:
            return {}
        records = PersonalDataFieldValue.objects.filter(
            facilitator_id__in=facilitator_ids, field_id__in=field_ids
        ).select_related("field")
        result: dict[int, dict[str, str | list[str] | bool]] = {}
        for hpd in records:
            if hpd.facilitator_id is not None:
                result.setdefault(hpd.facilitator_id, {})[hpd.field.slug] = hpd.value
        return result

    @staticmethod
    def list_field_ids_for_facilitator_event(
        facilitator_id: int, event_id: int
    ) -> list[int]:
        return list(
            PersonalDataFieldValue.objects.filter(
                facilitator_id=facilitator_id, event_id=event_id
            ).values_list("field_id", flat=True)
        )

    @staticmethod
    def delete_by_facilitators(facilitator_ids: list[int]) -> None:
        PersonalDataFieldValue.objects.filter(
            facilitator_id__in=facilitator_ids
        ).delete()

    @staticmethod
    def delete_for_facilitator_fields(facilitator_id: int, field_ids: list[int]) -> int:
        if not field_ids:
            return 0
        deleted, _ = PersonalDataFieldValue.objects.filter(
            facilitator_id=facilitator_id, field_id__in=field_ids
        ).delete()
        return deleted


def _import_log_entry_dto(entry: ImportLogEntry) -> ImportLogEntryDTO:
    return ImportLogEntryDTO(
        pk=entry.pk,
        integration_id=entry.integration_id,
        row_index=entry.row_index,
        status=ImportLogStatus(entry.status),
        reason=entry.reason or "",
        response_json=entry.response_json or "{}",
        title=entry.title or "",
        display_name=entry.display_name or "",
        session_id=entry.session_id,
        attempted_at=entry.attempted_at,
    )


class ImportLogEntryRepository(ImportLogEntryRepositoryProtocol):
    @staticmethod
    def upsert(data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        # One log entry per (integration, row_index): each attempt overwrites
        # the prior entry for that row, preserving the row's identity but
        # reflecting the latest status, reason, response snapshot, and
        # session FK. `attempted_at` resets to "now" on every upsert.
        defaults = {
            "status": data.status.value,
            "reason": data.reason,
            "response_json": data.response_json,
            "title": data.title,
            "display_name": data.display_name,
            "session_id": data.session_id,
            "attempted_at": django_timezone.now(),
        }
        entry, _ = ImportLogEntry.objects.update_or_create(
            integration_id=data.integration_id,
            row_index=data.row_index,
            defaults=defaults,
        )
        return _import_log_entry_dto(entry)

    @staticmethod
    def list_for_integration(
        integration_pk: int, *, status: ImportLogStatus | None = None, search: str = ""
    ) -> list[ImportLogEntryDTO]:
        qs = ImportLogEntry.objects.filter(integration_id=integration_pk)
        if status is not None:
            qs = qs.filter(status=status.value)
        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(display_name__icontains=search)
            )
        return [_import_log_entry_dto(e) for e in qs.order_by("-attempted_at", "-pk")]

    @staticmethod
    def for_session(session_pk: int) -> ImportLogEntryDTO | None:
        # Each session has at most one log entry — the row that produced it.
        # Returns None if no log entry points at this session.
        entry = ImportLogEntry.objects.filter(session_id=session_pk).first()
        return _import_log_entry_dto(entry) if entry is not None else None

    @staticmethod
    def read(pk: int) -> ImportLogEntryDTO:
        try:
            entry = ImportLogEntry.objects.get(pk=pk)
        except ImportLogEntry.DoesNotExist as exc:
            raise NotFoundError from exc
        return _import_log_entry_dto(entry)
