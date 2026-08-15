import logging
from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.links.db.django.models import Track
from tests.integration.conftest import EventFactory

rename_duplicate_track_names = import_module(
    "ludamus.links.db.django.migrations.0147_track_unique_name_per_event"
).rename_duplicate_track_names


def _apps_before_0147():
    return (
        MigrationLoader(connection)
        .project_state(("db_main", "0146_facilitator_is_collective"))
        .apps
    )


@pytest.fixture
def _duplicate_names_allowed():
    # No teardown: `django_db` rolls the whole test back, schema change
    # included. A transactional test in this class would have to recreate it.
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX track_unique_name_per_event")


@pytest.mark.django_db
@pytest.mark.usefixtures("_duplicate_names_allowed")
class TestRenameDuplicateTrackNames:
    def test_keeps_the_oldest_and_counts_the_rest_up(self, event, caplog):
        first = Track.objects.create(event=event, name="RPG", slug="rpg")
        second = Track.objects.create(event=event, name="rpg", slug="rpg-2")
        third = Track.objects.create(event=event, name="RpG", slug="rpg-3")

        with caplog.at_level(logging.INFO):
            rename_duplicate_track_names(_apps_before_0147(), None)

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        assert first.name == "RPG"
        assert second.name == "rpg (2)"
        assert third.name == "RpG (3)"
        assert "0147: 2 tracks renamed" in caplog.text

    def test_skips_counters_already_taken(self, event):
        Track.objects.create(event=event, name="RPG", slug="rpg")
        Track.objects.create(event=event, name="RPG (2)", slug="rpg-2")
        duplicate = Track.objects.create(event=event, name="rpg", slug="rpg-3")

        rename_duplicate_track_names(_apps_before_0147(), None)

        duplicate.refresh_from_db()
        assert duplicate.name == "rpg (3)"

    def test_leaves_a_counter_name_a_later_track_still_holds(self, event):
        Track.objects.create(event=event, name="RPG", slug="rpg")
        duplicate = Track.objects.create(event=event, name="rpg", slug="rpg-2")
        distinct = Track.objects.create(event=event, name="RPG (2)", slug="rpg-3")

        rename_duplicate_track_names(_apps_before_0147(), None)

        duplicate.refresh_from_db()
        distinct.refresh_from_db()
        assert duplicate.name == "rpg (3)"
        assert distinct.name == "RPG (2)"

    def test_truncates_to_the_column_width(self, event):
        long_name = "a" * 255
        Track.objects.create(event=event, name=long_name, slug="long")
        duplicate = Track.objects.create(event=event, name=long_name, slug="long-2")

        rename_duplicate_track_names(_apps_before_0147(), None)

        duplicate.refresh_from_db()
        assert duplicate.name == "a" * 251 + " (2)"

    def test_leaves_distinct_names_and_other_events_alone(self, event, sphere, caplog):
        other_event = EventFactory(sphere=sphere)
        alpha = Track.objects.create(event=event, name="Alpha", slug="alpha")
        beta = Track.objects.create(event=event, name="Beta", slug="beta")
        elsewhere = Track.objects.create(event=other_event, name="Alpha", slug="alpha")

        with caplog.at_level(logging.INFO):
            rename_duplicate_track_names(_apps_before_0147(), None)

        alpha.refresh_from_db()
        beta.refresh_from_db()
        elsewhere.refresh_from_db()
        assert alpha.name == "Alpha"
        assert beta.name == "Beta"
        assert elsewhere.name == "Alpha"
        assert "0147: 0 tracks renamed" in caplog.text
