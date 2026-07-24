from django.db.models import Count

from ludamus.links.db.django.models import Session, SessionBookmark
from ludamus.pacts.bookmarks import BookmarkRepositoryProtocol, BookmarkToggleDTO


class BookmarkRepository(BookmarkRepositoryProtocol):
    @staticmethod
    def toggle(
        *, user_id: int, session_id: int, sphere_id: int
    ) -> BookmarkToggleDTO | None:
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
        return BookmarkToggleDTO(
            bookmarked=not deleted,
            count=SessionBookmark.objects.filter(session_id=session_id).count(),
        )

    @staticmethod
    def bookmarked_session_ids(*, user_id: int, event_id: int) -> set[int]:
        return set(
            SessionBookmark.objects.filter(
                user_id=user_id, session__event_id=event_id
            ).values_list("session_id", flat=True)
        )

    @staticmethod
    def bookmark_counts(*, event_id: int) -> dict[int, int]:
        return dict(
            SessionBookmark.objects.filter(session__event_id=event_id)
            .values("session_id")
            .annotate(count=Count("id"))
            .values_list("session_id", "count")
        )
