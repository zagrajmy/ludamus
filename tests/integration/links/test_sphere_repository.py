import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ludamus.links.db.django.repositories import SphereRepository
from ludamus.pacts import NotFoundError, SiteDTO, SphereDTO
from tests.integration.conftest import PNG_BYTES


class TestSphereRepositoryDomainExists:
    def test_returns_true_for_matching_domain(self, sphere):
        assert SphereRepository.domain_exists(sphere.site.domain) is True

    def test_returns_false_for_unknown_domain(self):
        assert SphereRepository.domain_exists("no-such-domain.example") is False


class TestSphereRepositoryRead:
    def test_returns_sphere_with_embedded_site(self, sphere):
        result = SphereRepository.read(sphere.pk)

        assert result == SphereDTO.model_validate(sphere)
        assert result.site == SiteDTO.model_validate(sphere.site)

    def test_raises_not_found_for_unknown_pk(self):
        with pytest.raises(NotFoundError):
            SphereRepository.read(999_999)

    def test_single_query(self, sphere, django_assert_num_queries):
        with django_assert_num_queries(1):
            SphereRepository.read(sphere.pk)


class TestSphereRepositoryLogoUpdate:
    def test_replacing_logo_deletes_previous_file(self, sphere):
        sphere.logo = SimpleUploadedFile("old.png", PNG_BYTES, content_type="image/png")
        sphere.save()
        storage = sphere.logo.storage
        old_name = sphere.logo.name
        new_logo = SimpleUploadedFile("new.png", PNG_BYTES, content_type="image/png")

        SphereRepository.update(sphere.pk, {"logo": new_logo})

        sphere.refresh_from_db()
        assert sphere.logo.name != old_name
        assert not storage.exists(old_name)

    def test_clearing_logo_deletes_stored_file(self, sphere):
        sphere.logo = SimpleUploadedFile("old.png", PNG_BYTES, content_type="image/png")
        sphere.save()
        storage = sphere.logo.storage
        old_name = sphere.logo.name

        SphereRepository.update(sphere.pk, {"logo": ""})

        sphere.refresh_from_db()
        assert not sphere.logo
        assert not storage.exists(old_name)
