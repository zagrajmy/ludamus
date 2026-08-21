from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import translation

from ludamus.adapters.web.django.templatetags.date_tags import short_date

FRIDAY = datetime(2026, 9, 4, 16, 0, tzinfo=ZoneInfo("Europe/Warsaw"))


def test_short_date_abbreviates_weekday_and_month() -> None:
    with translation.override("en"):
        assert short_date(FRIDAY) == "Fri 4 Sep"


def test_short_date_lowercases_the_polish_month() -> None:
    with translation.override("pl"):
        assert short_date(FRIDAY) == "Pt 4 wrz"
