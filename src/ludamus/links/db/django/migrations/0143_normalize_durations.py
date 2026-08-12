import logging
import re

from django.db import migrations

logger = logging.getLogger(__name__)

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
    # The old value is overwritten in place, so the log is the only record of
    # what a row said before. Deploy output is what "which sessions lost their
    # length?" gets answered from.
    sessions_changed = sessions_emptied = 0
    for session in session_model.objects.exclude(duration="").iterator():
        if (normalized := _normalize(session.duration)) != session.duration:
            logger.info(
                "0143: session %s duration %r -> %r",
                session.pk,
                session.duration,
                normalized,
            )
            sessions_changed += 1
            sessions_emptied += not normalized
            session.duration = normalized
            session.save(update_fields=["duration"])

    category_model = apps.get_model("db_main", "ProposalCategory")
    categories_changed = entries_dropped = 0
    for category in category_model.objects.iterator():
        normalized_durations = [
            normalized
            for duration in category.durations or []
            if (normalized := _normalize(duration))
        ]
        if normalized_durations != category.durations:
            logger.info(
                "0143: category %s durations %r -> %r",
                category.pk,
                category.durations,
                normalized_durations,
            )
            categories_changed += 1
            entries_dropped += len(category.durations or []) - len(normalized_durations)
            category.durations = normalized_durations
            category.save(update_fields=["durations"])

    logger.info(
        "0143: %s sessions rewritten (%s emptied), %s categories rewritten"
        " (%s entries dropped)",
        sessions_changed,
        sessions_emptied,
        categories_changed,
        entries_dropped,
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0142_guild_guildmembership")]

    operations = [
        migrations.RunPython(normalize_stored_durations, migrations.RunPython.noop)
    ]
