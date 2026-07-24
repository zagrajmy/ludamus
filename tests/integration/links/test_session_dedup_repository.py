from ludamus.links.db.django.repositories import SessionRepository
from tests.integration.conftest import SessionFactory


class TestFindIdsByTitleAndEmail:
    def test_returns_only_sessions_without_ident(self):
        # Regression: a session that already carries an ident must never be
        # matched by the legacy title+email fallback, or a distinct row would
        # adopt it and clobber the existing ident.
        legacy = SessionFactory(title="Talk", contact_email="a@x.z", ident="")
        SessionFactory(
            title="Talk",
            contact_email="a@x.z",
            ident="already-idented",
            category=legacy.category,
        )

        ids = SessionRepository.find_ids_by_title_and_email(
            event_id=legacy.event_id, title="Talk", contact_email="a@x.z"
        )

        assert ids == [legacy.pk]
