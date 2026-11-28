"""Rewrite email-shaped public names to their local-part.

Auth0 password signup historically copied the email into User.name, and
session proposals then stored that as facilitator_name. Public UI now
sanitises on read; this migration also cleans the stored values so panel
edits and exports stop carrying the address.
"""

from __future__ import annotations

from django.db import migrations


def _looks_like_email(value: str) -> bool:
    text = value.strip()
    if text.count("@") != 1 or " " in text:
        return False
    local, _, domain = text.partition("@")
    return bool(local) and "." in domain


def _local_part(value: str) -> str:
    return value.strip().partition("@")[0].strip()


def scrub_forward(apps, schema_editor) -> None:
    User = apps.get_model("db_main", "User")
    Session = apps.get_model("db_main", "Session")
    for user in User.objects.exclude(name="").iterator():
        if _looks_like_email(user.name):
            user.name = _local_part(user.name)
            user.save(update_fields=["name"])
    for session in Session.objects.exclude(facilitator_name="").iterator():
        if _looks_like_email(session.facilitator_name):
            session.facilitator_name = _local_part(session.facilitator_name)
            session.save(update_fields=["facilitator_name"])


def scrub_backward(apps, schema_editor) -> None:
    # Irreversible: the domain part of each address is gone.
    pass


class Migration(migrations.Migration):
    dependencies = [("db_main", "0203_listing_party")]

    operations = [migrations.RunPython(scrub_forward, scrub_backward)]
