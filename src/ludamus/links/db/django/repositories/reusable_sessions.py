from django.db.models import Prefetch

from ludamus.links.db.django.models import SessionFieldValue
from ludamus.links.db.django.repositories.sessions import sessions_run_by
from ludamus.pacts.propose import ReusableSessionDTO, ReusableSessionRepositoryProtocol


class ReusableSessionRepository(ReusableSessionRepositoryProtocol):
    @staticmethod
    def list_reusable(
        *, user_id: int, sphere_id: int, exclude_event_id: int, limit: int
    ) -> list[ReusableSessionDTO]:
        sessions = (
            sessions_run_by(user_id)
            .filter(event__sphere_id=sphere_id)
            .exclude(event_id=exclude_event_id)
            .select_related("event")
            .prefetch_related(
                Prefetch(
                    "field_values",
                    queryset=SessionFieldValue.objects.select_related("field"),
                )
            )
            .order_by("-event__start_time", "-creation_time")
        )
        # NOTE: a session proposed to several editions is offered once, from
        # its newest. Deduped over a window of `limit * 4` rows, so someone who
        # repeats one session more often than that may be offered fewer.
        seen: set[str] = set()
        found: list[ReusableSessionDTO] = []
        for session in sessions[: limit * 4]:
            if (key := session.title.strip().casefold()) in seen:
                continue
            seen.add(key)
            found.append(
                ReusableSessionDTO(
                    pk=session.pk,
                    title=session.title,
                    event_name=session.event.name,
                    description=session.description,
                    participants_limit=session.participants_limit,
                    min_age=session.min_age,
                    duration=session.duration,
                    field_values={
                        fv.field.slug: fv.value for fv in session.field_values.all()
                    },
                )
            )
            if len(found) == limit:
                break
        return found
