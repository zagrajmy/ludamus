"""Migrate tag data to session fields.

For each event's tag categories, create equivalent SessionField (SELECT,
is_multiple=True) with SessionFieldOptions, SessionFieldRequirements, and
SessionFieldValues.  Also wire up EventSettings.displayed_session_fields.
"""

from collections import defaultdict

from django.db import migrations
from django.utils.text import slugify


def _create_session_fields(
    apps, event_tag_categories, all_tag_categories, tags_by_category
):
    SessionField = apps.get_model("db_main", "SessionField")
    SessionFieldOption = apps.get_model("db_main", "SessionFieldOption")

    # Key: (event_id, tag_category_id) -> SessionField
    tc_to_sf = {}

    for event_id, tc_ids in event_tag_categories.items():
        existing_slugs = set(
            SessionField.objects.filter(event_id=event_id).values_list(
                "slug", flat=True
            )
        )
        max_order = (
            SessionField.objects.filter(event_id=event_id)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
            or 0
        )

        for tc_id in tc_ids:
            tc = all_tag_categories[tc_id]
            slug = slugify(tc.name)
            base_slug = slug
            counter = 2
            while slug in existing_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            existing_slugs.add(slug)

            max_order += 1
            sf = SessionField.objects.create(
                event_id=event_id,
                name=tc.name,
                question=tc.name,
                slug=slug,
                field_type="select",
                is_multiple=True,
                allow_custom=(tc.input_type == "type"),
                icon=tc.icon or "",
                is_public=True,
                order=max_order,
                help_text="",
                max_length=50,
            )
            tc_to_sf[event_id, tc_id] = sf

            for i, tag in enumerate(tags_by_category.get(tc_id, [])):
                SessionFieldOption.objects.create(
                    field=sf, label=tag.name, value=tag.name, order=i
                )

    return tc_to_sf


def _create_requirements(apps, tc_to_sf):
    """Create SessionFieldRequirements from ProposalCategory.tag_categories."""
    ProposalCategory = apps.get_model("db_main", "ProposalCategory")
    SessionFieldRequirement = apps.get_model("db_main", "SessionFieldRequirement")

    for pc in ProposalCategory.objects.prefetch_related("tag_categories").all():
        for tc in pc.tag_categories.all():
            sf = tc_to_sf.get((pc.event_id, tc.id))
            if sf:
                SessionFieldRequirement.objects.create(
                    category=pc, field=sf, is_required=False, order=sf.order
                )


def _wire_filterable_fields(apps, tc_to_sf):
    """Wire EventSettings.displayed_session_fields from Event.filterable_tag_categories."""
    Event = apps.get_model("db_main", "Event")
    EventSettings = apps.get_model("db_main", "EventSettings")

    for event in Event.objects.prefetch_related("filterable_tag_categories").all():
        ftc_ids = set(
            event.filterable_tag_categories.all().values_list("id", flat=True)
        )
        if not ftc_ids:
            continue

        settings, _created = EventSettings.objects.get_or_create(event=event)
        for tc_id in ftc_ids:
            sf = tc_to_sf.get((event.id, tc_id))
            if sf:
                settings.displayed_session_fields.add(sf)


def _migrate_session_tags(apps, tc_to_sf):
    """Copy Session.tags M2M into SessionFieldValues."""
    ProposalCategory = apps.get_model("db_main", "ProposalCategory")
    Session = apps.get_model("db_main", "Session")
    SessionFieldValue = apps.get_model("db_main", "SessionFieldValue")

    pc_tc_ids = {}
    pc_event_ids = {}
    for pc in ProposalCategory.objects.prefetch_related("tag_categories").all():
        pc_tc_ids[pc.pk] = set(pc.tag_categories.values_list("id", flat=True))
        pc_event_ids[pc.pk] = pc.event_id

    sessions_with_tags = (
        Session.objects.prefetch_related("tags").filter(tags__isnull=False).distinct()
    )
    values_to_create = []
    for session in sessions_with_tags:
        allowed_tc_ids = pc_tc_ids.get(session.category_id, set())
        event_id = pc_event_ids.get(session.category_id)
        if not event_id:
            continue

        tags_by_cat = defaultdict(list)
        for tag in session.tags.all():
            if tag.category_id in allowed_tc_ids:
                tags_by_cat[tag.category_id].append(tag.name)

        for tc_id, tag_names in tags_by_cat.items():
            sf = tc_to_sf.get((event_id, tc_id))
            if sf:
                values_to_create.append(
                    SessionFieldValue(session=session, field=sf, value=tag_names)
                )

    if values_to_create:
        SessionFieldValue.objects.bulk_create(values_to_create, ignore_conflicts=True)


def migrate_tags_to_session_fields(apps, _schema_editor):
    TagCategory = apps.get_model("db_main", "TagCategory")
    Tag = apps.get_model("db_main", "Tag")
    ProposalCategory = apps.get_model("db_main", "ProposalCategory")

    event_tag_categories = defaultdict(set)
    for pc in ProposalCategory.objects.prefetch_related("tag_categories").all():
        for tc in pc.tag_categories.all():
            event_tag_categories[pc.event_id].add(tc.id)

    all_tag_categories = {tc.id: tc for tc in TagCategory.objects.all()}
    tags_by_category = defaultdict(list)
    for tag in Tag.objects.filter(confirmed=True).order_by("name"):
        tags_by_category[tag.category_id].append(tag)

    tc_to_sf = _create_session_fields(
        apps, event_tag_categories, all_tag_categories, tags_by_category
    )
    _create_requirements(apps, tc_to_sf)
    _wire_filterable_fields(apps, tc_to_sf)
    _migrate_session_tags(apps, tc_to_sf)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0058_remove_proposal_model")]

    operations = [
        migrations.RunPython(
            migrate_tags_to_session_fields, reverse_code=migrations.RunPython.noop
        )
    ]
