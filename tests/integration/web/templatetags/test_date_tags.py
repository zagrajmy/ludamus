from datetime import UTC, datetime

from django.template import Context, Template
from django.utils import translation


def test_short_date_reads_the_same_clock_as_the_time_filter() -> None:
    # The two are printed side by side ("Sat Sep 5 at 0:30"), and Django only
    # moves a datetime into the active zone for a filter that says it expects
    # local time. Without that the day came from UTC and the hour from the
    # site's zone, so a window opening just after local midnight was announced
    # on the day before.
    just_before_midnight_utc = datetime(2026, 9, 4, 22, 30, tzinfo=UTC)
    template = Template(
        '{% load date_tags %}{{ when|short_date }} {{ when|time:"G:i" }}'
    )

    with translation.override("en"):
        rendered = template.render(Context({"when": just_before_midnight_utc}))

    assert rendered == "Sat Sep 5 0:30"
