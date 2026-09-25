from django.db.models import Count, Q, QuerySet

from ludamus.links.db.django.models import Session, SessionBookmark
from ludamus.pacts.bookmarks import BookmarkRepositoryProtocol, BookmarkStateDTO
from ludamus.pacts.ids import EventId, SessionId, SphereId, UserId


class BookmarkRepository(BookmarkRepositoryProtocol):
    @staticmethod
    def toggle(
        *, user_id: UserId, session_id: SessionId, sphere_id: SphereId
    ) -> BookmarkStateDTO | None:
        # Resolve the session within the viewer's sphere so a bookmark can't be
        # forged against a session that isn't visible here.
        if not Session.objects.filter(
            id=session_id, event__sphere_id=sphere_id
        ).exists():
            return None
        # Delete-if-exists else create, driven by the delete count, so concurrent
        # toggles stay race-safe against the unique constraint.
        deleted, __ = SessionBookmark.objects.filter(
            user_id=user_id, session_id=session_id
        ).delete()
        if not deleted:
            SessionBookmark.objects.get_or_create(
                user_id=user_id, session_id=session_id
            )
        # The fresh total rides back so the client can paint the real number
        # instead of guessing with ±1 arithmetic on the DOM.
        return _state(
            SessionBookmark.objects.filter(session_id=session_id), user_id=user_id
        )

    @staticmethod
    def bookmarked_session_ids(*, user_id: UserId, event_id: EventId) -> set[SessionId]:
        return {
            SessionId(pk)
            for pk in SessionBookmark.objects.filter(
                user_id=user_id, session__event_id=event_id
            ).values_list("session_id", flat=True)
        }

    @staticmethod
    def bookmark_counts(*, event_id: EventId) -> dict[SessionId, int]:
        return {
            SessionId(sid): count
            for sid, count in (
                SessionBookmark.objects.filter(session__event_id=event_id)
                .values("session_id")
                .annotate(count=Count("id"))
                .values_list("session_id", "count")
            )
        }

    @staticmethod
    def session_state(
        *, user_id: UserId | None, session_id: SessionId, event_id: EventId
    ) -> BookmarkStateDTO:
        return _state(
            SessionBookmark.objects.filter(
                session_id=session_id, session__event_id=event_id
            ),
            user_id=user_id,
        )


def _state(
    bookmarks: QuerySet[SessionBookmark], *, user_id: UserId | None
) -> BookmarkStateDTO:
    state = bookmarks.aggregate(
        count=Count("id"), mine=Count("id", filter=Q(user_id=user_id))
    )
    return BookmarkStateDTO(bookmarked=bool(state["mine"]), count=state["count"])
