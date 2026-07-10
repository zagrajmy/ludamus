import pytest

from ludamus.links.db.django.repositories import SphereRepository
from ludamus.pacts import NotFoundError, SiteDTO, SphereDTO


class TestSphereRepositoryDomainExists:
    def test_returns_true_for_matching_domain(self, sphere):
        assert SphereRepository.domain_exists(sphere.site.domain) is True

    def test_returns_false_for_unknown_domain(self):
        assert SphereRepository.domain_exists("no-such-domain.example") is False


class TestSphereRepositoryReadWithSite:
    def test_returns_sphere_and_site(self, sphere):
        result_sphere, result_site = SphereRepository.read_with_site(sphere.pk)

        assert result_sphere == SphereDTO.model_validate(sphere)
        assert result_site == SiteDTO.model_validate(sphere.site)

    def test_raises_not_found_for_unknown_pk(self):
        with pytest.raises(NotFoundError):
            SphereRepository.read_with_site(999_999)

    def test_single_query(self, sphere, django_assert_num_queries):
        with django_assert_num_queries(1):
            SphereRepository.read_with_site(sphere.pk)
