from ludamus.adapters.db.django.models import Session, SessionBookmark
from ludamus.pacts.bookmarks import BookmarkRepositoryProtocol


class BookmarkRepository(BookmarkRepositoryProtocol):
    @staticmethod
    def toggle(*, user_id: int, session_id: int, sphere_id: int) -> bool | None:
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
        if deleted:
            return False
        SessionBookmark.objects.get_or_create(user_id=user_id, session_id=session_id)
        return True

    @staticmethod
    def bookmarked_session_ids(*, user_id: int, event_id: int) -> set[int]:
        return set(
            SessionBookmark.objects.filter(
                user_id=user_id, session__event_id=event_id
            ).values_list("session_id", flat=True)
        )
