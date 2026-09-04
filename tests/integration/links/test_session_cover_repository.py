from django.core.files.uploadedfile import SimpleUploadedFile

from ludamus.links.db.django.repositories import SessionRepository
from tests.integration.conftest import PNG_BYTES


class TestSessionRepositoryCoverUpdate:
    def test_replacing_cover_deletes_previous_file(
        self, agenda_item, django_capture_on_commit_callbacks
    ):
        session = agenda_item.session
        session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        session.save()
        storage = session.cover_image.storage
        old_name = session.cover_image.name
        new_image = SimpleUploadedFile("new.png", PNG_BYTES, content_type="image/png")

        # The old blob goes only once the row change is committed.
        with django_capture_on_commit_callbacks(execute=True):
            SessionRepository.update(session.pk, {"cover_image": new_image})

        session.refresh_from_db()
        assert session.cover_image.name != old_name
        assert not storage.exists(old_name)
