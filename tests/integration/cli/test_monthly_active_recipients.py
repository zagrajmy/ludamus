from datetime import UTC, datetime
from io import StringIO

from django.core.management import call_command
from freezegun import freeze_time

from ludamus.links.db.django.models import SessionParticipation
from ludamus.pacts.enrollment import SessionParticipationStatus
from tests.integration.conftest import UserFactory


@freeze_time("2026-11-12 10:00:00")
def test_prints_each_full_month_and_their_average(session):
    signed_in = UserFactory(last_login=datetime(2026, 10, 3, tzinfo=UTC))
    UserFactory(last_login=datetime(2026, 11, 2, tzinfo=UTC))
    UserFactory(last_login=datetime(2026, 4, 30, tzinfo=UTC))
    enrolled = SessionParticipation.objects.create(
        session=session, user=signed_in, status=SessionParticipationStatus.CONFIRMED
    )
    SessionParticipation.objects.filter(pk=enrolled.pk).update(
        creation_time=datetime(2026, 10, 20, tzinfo=UTC)
    )
    other = SessionParticipation.objects.create(
        session=session, user=UserFactory(), status=SessionParticipationStatus.CONFIRMED
    )
    SessionParticipation.objects.filter(pk=other.pk).update(
        creation_time=datetime(2026, 5, 1, tzinfo=UTC)
    )
    out = StringIO()

    call_command("monthly_active_recipients", stdout=out)

    assert out.getvalue().splitlines() == [
        "2026-05\t1",
        "2026-06\t0",
        "2026-07\t0",
        "2026-08\t0",
        "2026-09\t0",
        "2026-10\t1",
        "average\t0.3",
    ]
