"""Data migration: create Facilitator for each Session with a presenter."""

from django.db import migrations
from django.utils.text import slugify


def populate_facilitators(apps, _schema_editor):
    Session = apps.get_model("db_main", "Session")
    Facilitator = apps.get_model("db_main", "Facilitator")
    HostPersonalData = apps.get_model("db_main", "HostPersonalData")

    # Cache: (event_id, user_id) -> Facilitator to avoid duplicates
    cache: dict[tuple[int, int], object] = {}

    for session in Session.objects.filter(
        presenter_id__isnull=False, category__isnull=False
    ).select_related("category__event"):
        event_id = session.category.event_id
        user_id = session.presenter_id
        key = (event_id, user_id)

        if key not in cache:
            base_slug = slugify(session.display_name) or "facilitator"
            slug = base_slug
            counter = 1
            while Facilitator.objects.filter(event_id=event_id, slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            facilitator = Facilitator.objects.create(
                event_id=event_id,
                user_id=user_id,
                display_name=session.display_name,
                slug=slug,
            )
            cache[key] = facilitator
        else:
            facilitator = cache[key]

        session.proposed_by = facilitator
        session.save(update_fields=["proposed_by"])
        session.facilitators.add(facilitator)

        # Migrate HostPersonalData rows for this user+event to facilitator
        HostPersonalData.objects.filter(user_id=user_id, event_id=event_id).update(
            facilitator=facilitator
        )


def reverse_populate(apps, _schema_editor):
    Session = apps.get_model("db_main", "Session")
    HostPersonalData = apps.get_model("db_main", "HostPersonalData")

    # Clear facilitator references
    Session.objects.all().update(proposed_by=None)
    HostPersonalData.objects.all().update(facilitator=None)
    # Facilitators will be removed by reversing the schema migration


class Migration(migrations.Migration):
    dependencies = [("db_main", "0061_facilitator_and_more")]

    operations = [migrations.RunPython(populate_facilitators, reverse_populate)]
