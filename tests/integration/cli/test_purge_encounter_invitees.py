from datetime import UTC, datetime, timedelta
from io import StringIO

from django.core.management import call_command

from ludamus.links.db.django.models import EncounterInvitee, EncounterInviteMailing
from ludamus.pacts.encounter import InviteeStatus
from tests.integration.conftest import EncounterFactory, EncounterInviteeFactory

_DAY_AND_A_BIT = timedelta(days=1, hours=1)


def _invitee(encounter, *, status, age):
    invitee = EncounterInviteeFactory(encounter=encounter, status=status)
    EncounterInvitee.objects.filter(pk=invitee.pk).update(
        creation_time=datetime.now(UTC) - age
    )
    return invitee.email


class TestPurgeEncounterInvitees:
    def test_drops_unlisted_rows_past_the_window_and_rows_of_long_over_encounters(
        self, sphere, active_user
    ):
        encounter = EncounterFactory(sphere=sphere, creator=active_user)
        gone = EncounterFactory(sphere=sphere, creator=active_user)
        removed_old = _invitee(
            encounter, status=InviteeStatus.REMOVED, age=_DAY_AND_A_BIT
        )
        orphaned_old = _invitee(gone, status=InviteeStatus.INVITED, age=_DAY_AND_A_BIT)
        gone.delete()
        removed_today = _invitee(
            encounter, status=InviteeStatus.REMOVED, age=timedelta(hours=1)
        )
        listed_old = _invitee(
            encounter, status=InviteeStatus.DECLINED, age=_DAY_AND_A_BIT
        )
        long_over = EncounterFactory(
            sphere=sphere,
            creator=active_user,
            start_time=datetime.now(UTC) - timedelta(days=40),
            end_time=None,
        )
        of_long_over = _invitee(
            long_over, status=InviteeStatus.ACCEPTED, age=timedelta(days=41)
        )

        EncounterInviteMailing.objects.create(creator=active_user, count=5)
        EncounterInviteMailing.objects.filter(creator=active_user).update(
            creation_time=datetime.now(UTC) - _DAY_AND_A_BIT
        )
        EncounterInviteMailing.objects.create(creator=active_user, count=7)
        out = StringIO()

        call_command("purge_encounter_invitees", stdout=out)

        assert "Purged 4 stale encounter invitee(s)." in out.getvalue()
        remaining = set(EncounterInvitee.objects.values_list("email", flat=True))
        assert remaining == {removed_today, listed_old}
        assert not remaining & {removed_old, orphaned_old, of_long_over}
        assert list(EncounterInviteMailing.objects.values_list("count", flat=True)) == [
            7
        ]
