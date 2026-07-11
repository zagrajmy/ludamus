"""Archive Session.needs / Session.requirements into secret SessionFields.

Past-event data only: for each event holding sessions with a non-empty value,
create one secret (is_public=False) TEXT SessionField and copy each session's
text into a SessionFieldValue. No SessionFieldRequirement — the fields are
archival, not re-editable.
"""

from collections import defaultdict

from django.db import migrations
from django.utils.text import slugify

# (Session attribute, field label)
FIELDS = (("needs", "Zapotrzebowanie"), ("requirements", "Wymagania"))


def _unique_slug(existing_slugs, base):
    slug = base
    counter = 2
    while slug in existing_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    existing_slugs.add(slug)
    return slug


def migrate(apps, _schema_editor):
    Session = apps.get_model("db_main", "Session")
    SessionField = apps.get_model("db_main", "SessionField")
    SessionFieldValue = apps.get_model("db_main", "SessionFieldValue")

    for attr, label in FIELDS:
        by_event = defaultdict(list)
        for row in Session.objects.exclude(**{attr: ""}).values("id", "event_id", attr):
            by_event[row["event_id"]].append((row["id"], row[attr]))

        values_to_create = []
        for event_id, rows in by_event.items():
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
            field = SessionField.objects.create(
                event_id=event_id,
                name=label,
                question=label,
                slug=_unique_slug(existing_slugs, slugify(label)),
                field_type="text",
                is_multiple=False,
                allow_custom=False,
                icon="",
                is_public=False,
                order=max_order + 1,
                help_text="",
                max_length=50,
            )
            values_to_create.extend(
                SessionFieldValue(session_id=session_id, field_id=field.id, value=text)
                for session_id, text in rows
            )

        if values_to_create:
            SessionFieldValue.objects.bulk_create(
                values_to_create, ignore_conflicts=True
            )


class Migration(migrations.Migration):
    dependencies = [
        ("db_main", "0120_rename_hostpersonaldata_personaldatafieldvalue_and_more")
    ]

    operations = [migrations.RunPython(migrate, reverse_code=migrations.RunPython.noop)]
