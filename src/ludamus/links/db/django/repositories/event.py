from datetime import UTC, datetime

from ludamus.links.db.django.models import Event, Session
from ludamus.pacts.event import LandingStatsDTO, LandingStatsRepositoryProtocol


class LandingStatsRepository(LandingStatsRepositoryProtocol):
    @staticmethod
    def count_landing_stats() -> LandingStatsDTO:
        now = datetime.now(tz=UTC)
        return LandingStatsDTO(
            events=Event.objects.filter(publication_time__lte=now).count(),
            sessions=Session.objects.filter(event__publication_time__lte=now).count(),
        )
