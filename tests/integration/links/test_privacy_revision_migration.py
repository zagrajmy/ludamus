import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.usefixtures("transactional_db")
class TestPrivacyRevisionMigration:
    def test_existing_accounts_receive_distinct_revisions_and_can_roll_back(self):
        before = [("db_main", "0182_user_age_band")]
        after = [("db_main", "0183_user_privacy_revision")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        old_user = executor.loader.project_state(before).apps.get_model(
            "db_main", "User"
        )
        first = old_user.objects.create(username="legacy-first", slug="legacy-first")
        second = old_user.objects.create(username="legacy-second", slug="legacy-second")
        legacy_pks = {first.pk, second.pk}
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new_user = executor.loader.project_state(after).apps.get_model(
                "db_main", "User"
            )
            revisions = list(
                new_user.objects.filter(pk__in=legacy_pks).values_list(
                    "privacy_revision", flat=True
                )
            )
            assert len(revisions) == len(legacy_pks)
            assert all(revisions)
            assert len(set(revisions)) == len(legacy_pks)

            executor.migrate(before)
            assert (
                set(
                    old_user.objects.filter(pk__in=legacy_pks).values_list(
                        "pk", flat=True
                    )
                )
                == legacy_pks
            )
        finally:
            MigrationExecutor(connection).migrate(after)
