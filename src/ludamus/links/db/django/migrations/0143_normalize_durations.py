import re

from django.db import migrations

# Frozen copy of `pacts.durations.normalize_duration` as it stood when this
# migration was written. A migration that called the live function would
# rewrite data differently on every environment that ran it after the parsing
# rules changed; historical migrations have to stay reproducible.
_LOOSE_DURATION_RE = re.compile(
    r"p?t?\s*(?:(?P<hours>\d+)\s*h(?:ours?|rs?)?)?"
    r"\s*(?:(?P<minutes>\d+)\s*m(?:inutes?|ins?)?)?"
)
MINUTES_PER_HOUR = 60


def _normalize(text):
    if not (match := _LOOSE_DURATION_RE.fullmatch((text or "").strip().lower())):
        return ""
    carried, minutes = divmod(int(match["minutes"] or 0), MINUTES_PER_HOUR)
    hours = int(match["hours"] or 0) + carried
    if not hours and not minutes:
        return ""
    return "PT" + (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "")


def normalize_stored_durations(apps, schema_editor):
    del schema_editor
    # Durations reached storage as whatever their author typed ("P4H",
    # "50min", "110m"). Rewrite them in the one format readers understand;
    # anything unreadable becomes unset rather than shown raw.
    session_model = apps.get_model("db_main", "Session")
    # Soft-deleted rows included: `apps.get_model` drops the `AliveManager`
    # (it sets no `use_in_migrations`), so `objects` here is a plain manager
    # that sees every row — unlike `Session.objects` everywhere else. That is
    # what we want: restoring a session must not bring an unreadable duration
    # back with it.
    for session in session_model.objects.exclude(duration="").iterator():
        if (normalized := _normalize(session.duration)) != session.duration:
            session.duration = normalized
            session.save(update_fields=["duration"])

    category_model = apps.get_model("db_main", "ProposalCategory")
    for category in category_model.objects.iterator():
        normalized_durations = [
            normalized
            for duration in category.durations or []
            if (normalized := _normalize(duration))
        ]
        if normalized_durations != category.durations:
            category.durations = normalized_durations
            category.save(update_fields=["durations"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0142_guild_guildmembership")]

    operations = [
        migrations.RunPython(normalize_stored_durations, migrations.RunPython.noop)
    ]
