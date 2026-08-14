from django.db.models import F

from ludamus.links.db.django.models import Facilitator
from ludamus.pacts.legacy import FacilitatorDTO
from ludamus.pacts.panel import FacilitatorIdentityRepositoryProtocol


class FacilitatorIdentityRepository(FacilitatorIdentityRepositoryProtocol):
    @staticmethod
    def find_by_event_and_display_name(
        event_id: int, display_name: str
    ) -> FacilitatorDTO | None:
        facilitator = (
            Facilitator.objects.filter(event_id=event_id, display_name=display_name)
            .annotate(organizer_name=F("organizer__name"))
            .first()
        )
        if facilitator is None:
            return None
        return FacilitatorDTO.model_validate(facilitator)
