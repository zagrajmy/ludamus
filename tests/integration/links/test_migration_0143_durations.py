import logging
from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.links.db.django.models import Session
from tests.integration.conftest import ProposalCategoryFactory, SessionFactory

normalize_stored_durations = import_module(
    "ludamus.links.db.django.migrations.0143_normalize_durations"
).normalize_stored_durations


def _apps_before_0143():
    return (
        MigrationLoader(connection)
        .project_state(("db_main", "0142_guild_guildmembership"))
        .apps
    )


@pytest.mark.django_db
class TestNormalizeStoredDurations:
    def test_rewrites_what_it_can_read_and_empties_the_rest(self, caplog):
        session = SessionFactory.create(duration="P4H")
        unreadable = SessionFactory.create(duration="2h30")
        deleted = SessionFactory.create(duration="5 maja")
        deleted.soft_delete()
        category = ProposalCategoryFactory.create(durations=["1h", "junk", "PT30M"])

        with caplog.at_level(logging.INFO):
            normalize_stored_durations(_apps_before_0143(), None)

        session.refresh_from_db()
        unreadable.refresh_from_db()
        deleted = Session.all_objects.get(pk=deleted.pk)
        category.refresh_from_db()
        assert session.duration == "PT4H"
        assert not unreadable.duration
        assert not deleted.duration
        assert deleted.deleted_at is not None
        assert category.durations == ["PT1H", "PT30M"]
        assert (
            "0143: 3 sessions rewritten (2 emptied), 1 categories rewritten"
            " (1 entries dropped)" in caplog.text
        )
        assert "0143: session %s duration %r -> %r" in {
            record.msg for record in caplog.records
        }

    def test_leaves_canonical_values_alone(self, caplog):
        session = SessionFactory.create(duration="PT1H30M")

        with caplog.at_level(logging.INFO):
            normalize_stored_durations(_apps_before_0143(), None)

        session.refresh_from_db()
        assert session.duration == "PT1H30M"
        assert (
            "0143: 0 sessions rewritten (0 emptied), 0 categories rewritten"
            " (0 entries dropped)" in caplog.text
        )
