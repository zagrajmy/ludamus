from django.db.models import F, Prefetch, Window
from django.db.models.functions import Lower, RowNumber, Trim

from ludamus.links.db.django.models import SessionFieldValue
from ludamus.links.db.django.repositories.sessions import sessions_run_by
from ludamus.pacts.propose import ReusableSessionDTO, ReusableSessionRepositoryProtocol

_NEWEST_FIRST = (F("event__start_time").desc(), F("creation_time").desc())


class ReusableSessionRepository(ReusableSessionRepositoryProtocol):
    @staticmethod
    def list_reusable(
        *, user_id: int, sphere_id: int, exclude_event_id: int, limit: int
    ) -> list[ReusableSessionDTO]:
        sessions = (
            sessions_run_by(user_id)
            .filter(event__sphere_id=sphere_id)
            .exclude(event_id=exclude_event_id)
            .annotate(
                title_rank=Window(
                    RowNumber(),
                    partition_by=[Lower(Trim("title"))],
                    order_by=_NEWEST_FIRST,
                )
            )
            .filter(title_rank=1)
            .select_related("event")
            .prefetch_related(
                Prefetch(
                    "field_values",
                    queryset=SessionFieldValue.objects.select_related("field"),
                )
            )
            .order_by(*_NEWEST_FIRST)[:limit]
        )
        return [
            ReusableSessionDTO(
                pk=session.pk,
                title=session.title,
                event_name=session.event.name,
                description=session.description,
                participants_limit=session.participants_limit,
                min_age=session.min_age,
                duration=session.duration,
                field_values={
                    fv.field.slug: fv.value
                    for fv in session.field_values.all()
                    if fv.field.is_public or session.presenter_id == user_id
                },
            )
            for session in sessions
        ]
