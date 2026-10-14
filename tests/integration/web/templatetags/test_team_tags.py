from datetime import UTC, datetime, timedelta

from ludamus.gates.web.django.templatetags.team_tags import expires_in


class TestExpiresIn:
    def test_a_week_long_link_reads_in_days_alone(self) -> None:
        moment = datetime.now(UTC) + timedelta(days=6, hours=23)

        assert expires_in(moment) == "6\xa0days"

    def test_the_last_day_reads_in_hours(self) -> None:
        moment = datetime.now(UTC) + timedelta(hours=5, minutes=30)

        assert expires_in(moment) == "5\xa0hours"
