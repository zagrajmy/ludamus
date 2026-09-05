"""Which names of a session's answer somebody has already decided about."""

from ludamus.links.db.django.models import CofacilitatorResolution
from ludamus.pacts.panel import CofacilitatorResolutionRepositoryProtocol


class CofacilitatorResolutionRepository(CofacilitatorResolutionRepositoryProtocol):
    @staticmethod
    def list_fragments(*, session_id: int, field_id: int) -> list[str]:
        return list(
            CofacilitatorResolution.objects.filter(
                session_id=session_id, field_id=field_id
            ).values_list("fragment", flat=True)
        )

    @staticmethod
    def map_by_field(*, event_id: int, field_id: int) -> dict[int, list[str]]:
        rows = CofacilitatorResolution.objects.filter(
            field_id=field_id, session__event_id=event_id
        ).values_list("session_id", "fragment")
        fragments: dict[int, list[str]] = {}
        for session_id, fragment in rows:
            fragments.setdefault(session_id, []).append(fragment)
        return fragments

    @staticmethod
    def record(*, session_id: int, field_id: int, fragments: list[str]) -> None:
        # A name decided twice is the same decision, not a second one.
        CofacilitatorResolution.objects.bulk_create(
            [
                CofacilitatorResolution(
                    session_id=session_id, field_id=field_id, fragment=fragment
                )
                for fragment in fragments
            ],
            ignore_conflicts=True,
        )
