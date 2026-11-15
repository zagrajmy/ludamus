from datetime import UTC, datetime, timedelta
from io import StringIO

from django.core.management import call_command

from ludamus.links.db.django.models import ParleyReport
from tests.integration.conftest import UserFactory

_YEAR = timedelta(days=365)


def _report(sphere, reporter, *, message_id, written_at, body="Rude", author="Bo"):
    return ParleyReport.objects.create(
        sphere=sphere,
        reporter=reporter,
        room_id=f"sphere:{sphere.pk}",
        message_id=message_id,
        reason="Spam",
        reported_user=UserFactory(),
        author_name=author,
        body=body,
        written_at=written_at,
    )


def test_clears_the_words_of_messages_a_year_old_and_keeps_the_report(
    sphere, active_user
):
    now = datetime.now(UTC)
    old = _report(
        sphere, active_user, message_id=1, written_at=now - _YEAR - timedelta(hours=1)
    )
    young = _report(
        sphere, active_user, message_id=2, written_at=now - _YEAR + timedelta(hours=1)
    )
    # Cleared on an earlier run, and one the Worker could not copy at all.
    already = _report(
        sphere,
        active_user,
        message_id=3,
        written_at=now - 2 * _YEAR,
        body="",
        author="",
    )
    uncopied = _report(
        sphere, active_user, message_id=4, written_at=None, body="", author=""
    )
    record = (old.reason, old.reported_user_id, old.written_at)
    out = StringIO()

    call_command("forget_parley_report_copies", stdout=out)

    assert "Cleared the copied words of 1 reported chat message(s)." in out.getvalue()
    old.refresh_from_db()
    young.refresh_from_db()
    assert (old.body, old.author_name) == ("", "")
    assert (old.reason, old.reported_user_id, old.written_at) == record
    assert (young.body, young.author_name) == ("Rude", "Bo")
    assert set(ParleyReport.objects.values_list("pk", flat=True)) == {
        old.pk,
        young.pk,
        already.pk,
        uncopied.pk,
    }
